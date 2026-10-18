import time
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kb import idf, indexer
from kb.config import Config, ImapSource, SearchConfig, TelegramChat, TelegramSource
from kb.connectors import telegram
from kb.search import decay, rank, search

NOW = datetime(2026, 10, 10, tzinfo=UTC)
CFG = SearchConfig()


def row(i, days_ago, title="t"):
    return {
        "id": i,
        "title": title,
        "summary": None,
        "excerpt": "",
        "last_activity_at": NOW - timedelta(days=days_ago),
        "metadata": {},
    }


def test_decay_bounds():
    assert decay(NOW, NOW, CFG) == pytest.approx(1.0)
    assert CFG.decay_floor <= decay(NOW - timedelta(days=3650), NOW, CFG) < CFG.decay_floor + 0.01


def test_decay_prefers_recent_on_tie():
    old, new = row(1, 300), row(2, 7)
    ranked = rank([(old, 0.5), (new, 0.5)], "q", CFG, now=NOW)
    assert [r["id"] for r, _ in ranked] == [2, 1]


def test_decay_does_not_override_clear_relevance():
    old_but_right, new_noise = row(1, 365), row(2, 1)
    ranked = rank([(old_but_right, 1.0), (new_noise, 0.6)], "q", CFG, now=NOW)
    assert ranked[0][0]["id"] == 1


class WordReranker:
    def __init__(self, word, delay=0.0):
        self.word, self.delay = word, delay

    def scores(self, query, docs):
        time.sleep(self.delay)
        return [5.0 if self.word in d else -5.0 for d in docs]


def test_reranker_reorders_top():
    a, b = row(1, 1, "budget plan"), row(2, 1, "invoice from printer")
    ranked = rank([(a, 0.9), (b, 0.8)], "printer invoice", CFG, WordReranker("invoice"), now=NOW)
    assert ranked[0][0]["id"] == 2


def test_slow_reranker_falls_back_to_fused_order():
    a, b = row(1, 1, "budget plan"), row(2, 1, "invoice from printer")
    cfg = SearchConfig(rerank_budget_seconds=0.2)
    ranked = rank([(a, 0.9), (b, 0.8)], "q", cfg, WordReranker("invoice", delay=1.0), now=NOW)
    assert ranked[0][0]["id"] == 1


def test_context_has_matched_message_neighbours_and_deep_link(conn):
    src = TelegramSource(
        id="tg", type="telegram", chats=[TelegramChat(chat=-1001234, scopes=["rdim"])]
    )
    cfg = Config(sources=[src])
    chat = telegram.ChatInfo(chat_id=-1001234, title="Team", username=None, peer_type="channel")
    lines = ["hello all", "agenda later", "budget approved 5000", "great news", "see you", "bye"]
    t0 = datetime(2026, 9, 1, 10, tzinfo=UTC)
    for i, text in enumerate(lines, 1):
        msg = SimpleNamespace(
            id=i,
            date=t0 + timedelta(minutes=i),
            message=text,
            edit_date=None,
            sender=None,
            sender_id=7,
            reply_to=None,
            reactions=None,
            media=None,
        )
        telegram.on_message(conn, src, chat, msg)
    while indexer.run_once(conn, cfg):
        pass
    [hit] = search(conn, "budget approved")
    ctx = hit.extra["context"]
    assert [c["matched"] for c in ctx] == [False, False, True, False, False]
    assert ctx[2]["text"].endswith("budget approved 5000")
    assert hit.locator == "https://t.me/c/1234/3"  # the matched message itself


def test_gmail_deep_link(monkeypatch):
    monkeypatch.setenv("U", "digisoftou@gmail.com")
    monkeypatch.setenv("P", "x")
    cfg = Config(
        sources=[
            ImapSource(
                id="g", type="imap", host="imap.gmail.com", username_env="U", password_env="P"
            )
        ]
    )
    link = indexer.email_locator(
        cfg, "g", {"gm_thrid": "1", "folder": "x", "uid": 1}, "<abc.123@mail.x>"
    )
    assert link == (
        "https://mail.google.com/mail/?authuser=digisoftou@gmail.com"
        "#search/rfc822msgid:abc.123@mail.x"
    )
    plain = indexer.email_locator(cfg, "g", {"folder": "INBOX", "uid": 7}, "<m@x>")
    assert plain == "imap://g/INBOX;UID=7"


@pytest.mark.slow
def test_search_latency_p50_under_3s_on_seeded_50k_items(conn):
    conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,
                           participants, occurred_at, last_activity_at)
        SELECT 'seed', 'k' || g, 'tg_conversation', ARRAY['rdim'], 'Chat ' || (g % 50),
               'message ' || g || ' about ' || (ARRAY['budget','invoice','server','ads','prices',
               'contract','delivery','meeting'])[1 + g % 8] || ' word' || (g % 997) || ' token'
               || (g % 7919), '{}', now() - (g % 365) * interval '1 day',
               now() - (g % 365) * interval '1 day'
        FROM generate_series(1, 50000) AS g
        """
    )
    idf.refresh(conn)
    times = []
    for q in [
        "budget invoice",
        "word17",
        "server contract",
        "token7001",
        "order 4471",
        "prices delivery meeting",
        "ads",
        "word996 token1",
    ] * 3:
        t = time.perf_counter()
        search(conn, q)
        times.append(time.perf_counter() - t)
    times.sort()
    p50, p95 = times[len(times) // 2], times[int(len(times) * 0.95)]
    print(f"p50={p50:.3f}s p95={p95:.3f}s")
    assert p50 < 3.0 and p95 < 8.0


def test_ranking_method_is_reported():
    a, b = row(1, 1, "budget plan"), row(2, 1, "invoice from printer")
    rank([(a, 0.9), (b, 0.8)], "q", CFG, WordReranker("invoice"), now=NOW)
    assert a["_ranking"] == "rerank"
    c = row(3, 1)
    rank(
        [(c, 0.9)],
        "q",
        SearchConfig(rerank_budget_seconds=0.1),
        WordReranker("x", delay=0.5),
        now=NOW,
    )
    assert c["_ranking"] == "fused"
