from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from kb import embed, idf, indexer, passages
from kb.config import Config, EmbeddingConfig, TelegramChat, TelegramSource
from kb.connectors import telegram
from kb.search import recent, search
from tests.test_vectors import TrigramEmbedder

T0 = datetime(2026, 9, 1, 10, tzinfo=UTC)
CHAT = telegram.ChatInfo(chat_id=-1001, title="Logistics", username=None, peer_type="channel")
SRC = TelegramSource(
    id="tg",
    type="telegram",
    chats=[TelegramChat(chat=-1001, scopes=["quokka"])],
    max_unit_messages=1000,
)
CFG = Config(sources=[SRC], embedding=EmbeddingConfig(cache_dir="/nonexistent"))
DETAIL = (
    "Посилка застрягла на митниці в Львові через відсутній інвойс, трекінг 20450813456789; "
    "перевізник Meest повернув її на склад. Повторна відправка можлива лише після оплати мита "
    "та завантаження інвойсу в кабінет Meest. Брокер Олена каже, що декларацію треба подати "
    "заново, оскільки код товару вказали неправильно; вартість переоформлення 450 грн, "
    "строк два дні. Клієнту пообіцяли нову дату доставки в четвер."
)


def msg(i, text, author_id=7, minutes=None, reactions=0):
    sender = SimpleNamespace(first_name=f"U{author_id}", last_name="", username=None)
    react = SimpleNamespace(results=[SimpleNamespace(count=reactions)]) if reactions else None
    return SimpleNamespace(
        id=i,
        date=T0 + timedelta(minutes=minutes if minutes is not None else i),
        message=text,
        edit_date=None,
        sender=sender,
        sender_id=author_id,
        reply_to=None,
        reactions=react,
        media=None,
    )


def ingest(conn, msgs):
    for m in msgs:
        telegram.on_message(conn, SRC, CHAT, m)
    while indexer.run_once(conn, CFG):
        pass


def corpus(conn, n=60):
    """n separate one-message conversations (2 h apart) so rarity statistics are meaningful."""
    ingest(
        conn,
        [msg(5000 + i, f"ок, дякую, все добре {i % 3}", minutes=-120 * (i + 1)) for i in range(n)],
    )
    idf.refresh(conn)


def chatter(n, start=1):
    return [msg(start + i, f"ок, дякую {i}", author_id=1 + i % 3) for i in range(n)]


def test_burst_gate_filler_rejected_rare_token_accepted_reaction_accepted(conn):
    corpus(conn)  # common words are common, everything else is rare
    assert passages.qualifies(conn, "ок, дякую, все добре " * 12, 0, True) is False  # filler
    assert passages.qualifies(conn, "short but rare: Meest", 0, True) is False  # < 200 chars
    assert passages.qualifies(conn, DETAIL, 0, True) is True  # rare tokens
    assert passages.qualifies(conn, "ок, дякую, все добре " * 12, 3, True) is True  # reactions
    assert passages.qualifies(conn, "ок " * 100, 0, False) is False  # no stats: needs 400 chars


def test_detail_buried_in_long_thread_found_via_passage(conn):
    corpus(conn)
    ingest(conn, [*chatter(60), msg(200, DETAIL, author_id=9, minutes=61)])
    [unit] = conn.execute(
        "SELECT * FROM items WHERE kind = 'tg_conversation' AND metadata->>'message_count' = '61'"
    ).fetchall()
    found = conn.execute("SELECT * FROM items WHERE kind = 'passage'").fetchall()
    assert len(found) == 1 and found[0]["metadata"]["parent_item_id"] == unit["id"]
    assert found[0]["scopes"] == ["quokka"]
    e = TrigramEmbedder()
    while embed.run_cycle(conn, CFG, e):
        pass
    hits = search(conn, "митниця повернула посилку на склад", embedder=e, limit=3)
    assert hits[0].item_id == unit["id"]  # reported as the conversation
    assert "Meest" in (hits[0].excerpt or "") or any(
        c["matched"] and "Meest" in c["text"] for c in hits[0].extra.get("context", [])
    )


def test_passages_follow_their_conversation(conn):
    ingest(conn, [*chatter(5), msg(50, DETAIL, author_id=9)])
    assert (
        conn.execute("SELECT count(*) AS n FROM items WHERE kind = 'passage'").fetchone()["n"] == 1
    )
    telegram.on_deleted(conn, SRC, CHAT.chat_id, [50])
    while indexer.run_once(conn, CFG):
        pass
    left = conn.execute(
        "SELECT count(*) AS n FROM items WHERE kind = 'passage' AND NOT hidden"
    ).fetchone()
    assert left["n"] == 0


def test_recent_activity_never_lists_passages(conn):
    ingest(conn, [*chatter(5), msg(50, DETAIL, author_id=9)])
    assert {e.kind for e in recent(conn)} == {"tg_conversation"}


def test_backfill_cycle_covers_old_units(conn):
    ingest(conn, [*chatter(5), msg(50, DETAIL, author_id=9)])
    conn.execute("DELETE FROM items WHERE kind = 'passage'")
    conn.execute("UPDATE items SET metadata = metadata - 'passages_v'")
    assert passages.backfill_cycle(conn) == 1
    assert passages.backfill_cycle(conn) == 0
    assert (
        conn.execute("SELECT count(*) AS n FROM items WHERE kind = 'passage'").fetchone()["n"] == 1
    )
