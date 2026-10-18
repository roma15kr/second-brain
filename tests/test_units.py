from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from kb import db, indexer
from kb.config import Config, TelegramChat, TelegramSource
from kb.connectors import imap, telegram
from kb.mcp_server import build_server
from kb.search import SearchError, recent, search
from kb.units import normalize_subject, strip_quoted
from tests.fakes import FakeImap, call, make_email

T0 = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)


def index_all(conn, config):
    while indexer.run_once(conn, config):
        pass


def items(conn, kind):
    return conn.execute(
        "SELECT * FROM items WHERE kind = %s AND NOT hidden ORDER BY occurred_at", (kind,)
    ).fetchall()


# --- email ---------------------------------------------------------------------------------


def mail(uid, subject, body, mid, date_s, refs=None, sender="oleh@quokka.example"):
    raw = make_email(subject, body, sender=sender, message_id=mid, date=date_s)
    if refs:
        raw = raw.replace(b"Subject:", f"References: {' '.join(refs)}\r\nSubject:".encode(), 1)
    return uid, raw


def ingest(conn, source, config, mails):
    fake = FakeImap()
    for uid, raw in mails:
        fake.add(uid, raw, datetime(2026, 9, 1))
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    index_all(conn, config)


def test_normalize_subject_and_strip_quoted():
    assert normalize_subject("RE: Fwd: Відп: Budget Q4") == "budget q4"
    assert normalize_subject("Re[2]: Budget  Q4") == "budget q4"
    body = "Yes, agreed.\n\nOn Mon, 1 Sep 2026 Oleh wrote:\n> old text\n> more"
    assert strip_quoted(body).strip() == "Yes, agreed."


def test_email_threads_from_references_and_fallback_subject(conn, source, config):
    ingest(
        conn,
        source,
        config,
        [
            mail(1, "Budget Q4", "Proposal 5000", "<a@x>", "Mon, 1 Sep 2026 10:00:00 +0300"),
            mail(
                2,
                "Re: Budget Q4",
                "Make it 7000",
                "<b@x>",
                "Mon, 1 Sep 2026 12:00:00 +0300",
                refs=["<a@x>"],
                sender="me@example.com",
            ),
            # no References, same subject and participants -> same thread by fallback
            mail(3, "RE: Budget Q4", "Final: 6000", "<c@x>", "Tue, 2 Sep 2026 09:00:00 +0300"),
            mail(4, "Lunch", "sounds good", "<d@x>", "Tue, 2 Sep 2026 09:00:00 +0300"),
        ],
    )
    threads = items(conn, "email_thread")
    assert [t["title"] for t in threads] == ["Budget Q4", "Lunch"]
    budget = threads[0]
    assert budget["metadata"]["message_count"] == 3
    assert (
        "5000" in budget["raw_text"]
        and "7000" in budget["raw_text"]
        and "6000" in budget["raw_text"]
    )
    assert budget["last_activity_at"] > budget["occurred_at"]
    [hit] = search(conn, "7000")
    assert hit.item_id == budget["id"]


def test_reply_yields_one_updated_result(conn, source, config):
    ingest(
        conn,
        source,
        config,
        [mail(1, "Contract", "draft attached", "<a@x>", "Mon, 1 Sep 2026 10:00:00 +0300")],
    )
    first = items(conn, "email_thread")[0]
    ingest(
        conn,
        source,
        config,
        [
            mail(1, "Contract", "draft attached", "<a@x>", "Mon, 1 Sep 2026 10:00:00 +0300"),
            mail(
                2,
                "Re: Contract",
                "signed",
                "<b@x>",
                "Wed, 3 Sep 2026 10:00:00 +0300",
                refs=["<a@x>"],
            ),
        ],
    )
    [thread] = items(conn, "email_thread")
    assert thread["id"] == first["id"]
    assert thread["last_activity_at"] > first["last_activity_at"]
    assert len(search(conn, "contract")) == 1


def test_out_of_order_reply_merges_threads(conn, source, config):
    ingest(
        conn,
        source,
        config,
        [
            mail(
                1,
                "Re: Offer",
                "accepted",
                "<b@x>",
                "Wed, 3 Sep 2026 10:00:00 +0300",
                refs=["<a@x>"],
                sender="me@example.com",
            ),
            mail(2, "Different words", "our offer", "<a@x>", "Mon, 1 Sep 2026 10:00:00 +0300"),
        ],
    )
    [thread] = items(conn, "email_thread")
    assert thread["metadata"]["message_count"] == 2


def test_subject_fallback_needs_shared_participants(conn, source, config):
    ingest(
        conn,
        source,
        config,
        [
            mail(
                1,
                "Invoice",
                "one",
                "<a@x>",
                "Mon, 1 Sep 2026 10:00:00 +0300",
                sender="a@one.example",
            ),
            mail(
                2,
                "Invoice",
                "two",
                "<b@x>",
                "Mon, 1 Sep 2026 11:00:00 +0300",
                sender="b@two.example",
            ),
        ],
    )
    # both share the recipient me@example.com, so they are participants in common
    assert len(items(conn, "email_thread")) == 1


# --- telegram -----------------------------------------------------------------------------

CHAT = telegram.ChatInfo(chat_id=-1001, title="Team", username=None, peer_type="channel")


@pytest.fixture
def tg():
    src = TelegramSource(
        id="tg",
        type="telegram",
        chats=[TelegramChat(chat=-1001, scopes=["rdim"])],
        gap_minutes=45,
        max_unit_messages=5,
    )
    return src, Config(sources=[src])


def tmsg(msg_id, text, at, reply_to=None, top=None, forum=False):
    reply = SimpleNamespace(reply_to_msg_id=reply_to, reply_to_top_id=top, forum_topic=forum)
    return SimpleNamespace(
        id=msg_id,
        date=at,
        message=text,
        edit_date=None,
        sender=None,
        sender_id=7,
        reply_to=reply if (reply_to or top or forum) else None,
        reactions=None,
        media=None,
    )


def send(conn, tg, *msgs):
    src, cfg = tg
    for m in msgs:
        telegram.on_message(conn, src, CHAT, m)
    index_all(conn, cfg)


def convs(conn):
    return items(conn, "tg_conversation")


def test_tg_segment_split_on_gap(conn, tg):
    send(
        conn,
        tg,
        tmsg(1, "morning standup", T0),
        tmsg(2, "ok", T0 + timedelta(minutes=10)),
        tmsg(3, "evening topic", T0 + timedelta(hours=3)),
    )
    c = convs(conn)
    assert [x["metadata"]["message_count"] for x in c] == [2, 1]


def test_tg_late_reply_joins_old_unit(conn, tg):
    send(
        conn,
        tg,
        tmsg(1, "who has the invoice?", T0),
        tmsg(2, "unrelated news", T0 + timedelta(hours=5)),
        tmsg(3, "I have it", T0 + timedelta(days=1), reply_to=1),
    )
    c = convs(conn)
    assert len(c) == 2
    first = next(x for x in c if "invoice" in x["raw_text"])
    assert "I have it" in first["raw_text"]
    assert first["last_activity_at"] == T0 + timedelta(days=1)


def test_tg_forum_topic_is_unit(conn, tg):
    send(
        conn,
        tg,
        tmsg(10, "design thread", T0, reply_to=100, forum=True),
        tmsg(11, "marketing thread", T0 + timedelta(minutes=1), reply_to=200, forum=True),
        tmsg(12, "design reply", T0 + timedelta(minutes=2), reply_to=10, top=100, forum=True),
    )
    c = convs(conn)
    assert len(c) == 2
    design = next(x for x in c if "design thread" in x["raw_text"])
    assert "design reply" in design["raw_text"] and "marketing" not in design["raw_text"]
    assert design["metadata"]["topic_id"] == 100


def test_tg_busy_chat_is_capped(conn, tg):
    send(conn, tg, *[tmsg(i, f"news {i}", T0 + timedelta(minutes=i)) for i in range(1, 8)])
    assert [x["metadata"]["message_count"] for x in convs(conn)] == [5, 2]


def test_tg_edit_and_delete_inside_conversation(conn, tg):
    src, cfg = tg
    send(conn, tg, tmsg(1, "price 5000", T0), tmsg(2, "agreed", T0 + timedelta(minutes=1)))
    edited = tmsg(1, "price 6000", T0)
    edited.edit_date = T0 + timedelta(minutes=5)
    send(conn, tg, edited)
    [c] = convs(conn)
    assert "6000" in c["raw_text"] and "5000" not in c["raw_text"]
    telegram.on_deleted(conn, src, CHAT.chat_id, [1])
    index_all(conn, cfg)
    [c] = convs(conn)
    assert "6000" not in c["raw_text"] and c["metadata"]["message_count"] == 1
    telegram.on_deleted(conn, src, CHAT.chat_id, [2])
    index_all(conn, cfg)
    assert convs(conn) == []


# --- tools ---------------------------------------------------------------------------------


async def test_get_item_pages_long_conversation(conn, pg_url, tg):
    src, _ = tg
    src.max_unit_messages = 1000
    send(conn, tg, *[tmsg(i, f"line {i}", T0 + timedelta(seconds=i)) for i in range(1, 301)])
    [c] = convs(conn)
    server = build_server(lambda: db.connect(pg_url))
    page = (await call(server, "get_item", {"item_id": c["id"]})).structured_content
    assert page["total_messages"] == 300 and len(page["messages"]) == 50
    assert page["next_offset"] == 50 and page["messages"][0]["text"].endswith("line 1")
    last = (await call(server, "get_item", {"item_id": c["id"], "offset": 250})).structured_content
    assert last["next_offset"] is None and last["messages"][-1]["text"].endswith("line 300")


async def test_get_item_unknown_id_is_clear(pg_url, conn):
    server = build_server(lambda: db.connect(pg_url))
    with pytest.raises(ToolError, match="no item with item_id 999999"):
        await call(server, "get_item", {"item_id": 999999})


def test_recent_activity_orders_by_last_activity(conn, tg, source, config):
    send(conn, tg, tmsg(1, "old chat", T0))
    ingest(
        conn,
        source,
        config,
        [mail(1, "Fresh mail", "hello", "<z@x>", "Fri, 5 Sep 2026 10:00:00 +0300")],
    )
    titles = [e.title for e in recent(conn)]
    assert titles == ["Fresh mail", "Team"]
    with pytest.raises(SearchError, match="valid scopes"):
        from kb.search import SearchFilters

        recent(conn, SearchFilters(scopes=["acme"]))
