import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from kb import distill, indexer
from kb.config import Config, LlmConfig, TelegramChat, TelegramSource
from kb.connectors import telegram
from kb.distill import Usage
from kb.search import search

T0 = datetime(2026, 9, 1, 10, tzinfo=UTC)
LATER = T0 + timedelta(days=1)  # "now" for settledness
CHAT = telegram.ChatInfo(chat_id=-1001, title="Ops chat", username=None, peer_type="channel")
LONG = "Обговорили запуск реклами на маркетплейсі, бюджет 5000 грн, старт в понеділок. " * 2


class StubClient:
    def __init__(self, scope="quokka", confidence=0.9):
        self.calls = []
        self.batches = {}
        self.scope, self.confidence = scope, confidence

    def result(self, text):
        return {
            "question": "коли старт реклами на маркетплейсі",
            "summary": "Погодили бюджет кампанії та дату старту.",
            "outcome": "Старт в понеділок",
            "entities": [{"type": "amount", "value": "5000 грн"}],
            "language": "uk",
            "scope_guess": self.scope,
            "scope_confidence": self.confidence,
        }

    def complete(self, model, system, text, effort):
        self.calls.append(text)
        return self.result(text), Usage(1000, 100)

    def submit_batch(self, model, system, effort, items):
        bid = f"batch_{len(self.batches) + 1}"
        self.batches[bid] = items
        return bid

    def batch_results(self, batch_id):
        items = self.batches[batch_id]
        return "completed", {
            cid: (self.result(t), Usage(900, 90), None) for cid, t in items.items()
        }


def setup(conn, scopes=None, n=1, text=LONG, **llm):
    src = TelegramSource(
        id="tg",
        type="telegram",
        scopes=["unsorted"],
        chats=[TelegramChat(chat=-1001, scopes=scopes)],
    )
    cfg = Config(sources=[src], llm=LlmConfig(**{"batch_threshold": 100, **llm}))
    for i in range(n):
        msg = SimpleNamespace(
            id=i + 1,
            date=T0 + timedelta(hours=3 * i),
            message=f"{text} #{i}",
            edit_date=None,
            sender=None,
            sender_id=7,
            reply_to=None,
            reactions=None,
            media=None,
        )
        telegram.on_message(conn, src, CHAT, msg)
    while indexer.run_once(conn, cfg):
        pass
    return src, cfg


def item(conn):
    return conn.execute("SELECT * FROM items WHERE NOT hidden ORDER BY id LIMIT 1").fetchone()


def test_only_settled_units_are_pending(conn):
    _, cfg = setup(conn)
    assert distill.pending(conn, cfg.llm, 10, now=T0 + timedelta(minutes=5)) == []
    assert len(distill.pending(conn, cfg.llm, 10, now=LATER)) == 1


def test_distill_fills_fields_and_summary_is_searchable(conn):
    _, cfg = setup(conn)
    client = StubClient()
    stats = distill.run_cycle(conn, cfg, client, now=LATER)
    assert stats["live"] == 1
    it = item(conn)
    assert it["summary"].startswith("Погодили") and it["outcome"] == "Старт в понеділок"
    assert it["language"] == "uk" and it["entities"][0]["value"] == "5000 грн"
    [hit] = search(conn, "Погодили")  # word only in the summary
    assert (
        hit.summary is not None
        and hit.summary.startswith("Погодили")
        and hit.extra["outcome"] == "Старт в понеділок"
    )
    assert distill.run_cycle(conn, cfg, client, now=LATER)["live"] == 0  # done, not pending
    assert len(client.calls) == 1


def test_low_confidence_is_unsorted(conn):
    _, cfg = setup(conn)
    distill.run_cycle(conn, cfg, StubClient(confidence=0.4), now=LATER)
    assert item(conn)["scopes"] == ["unsorted"]


def test_confident_guess_scopes_unsorted_item(conn):
    _, cfg = setup(conn)
    distill.run_cycle(conn, cfg, StubClient(scope="quokka", confidence=0.9), now=LATER)
    it = item(conn)
    assert it["scopes"] == ["quokka"] and it["metadata"]["scope_by"] == "classifier"


def test_scope_rule_beats_llm(conn):
    _, cfg = setup(conn, scopes=["rdim"])
    distill.run_cycle(conn, cfg, StubClient(scope="quokka", confidence=0.99), now=LATER)
    assert item(conn)["scopes"] == ["rdim"]


def test_rebuild_reuses_cache_without_new_requests(conn):
    _, cfg = setup(conn)
    client = StubClient()
    distill.run_cycle(conn, cfg, client, now=LATER)
    indexer.rebuild(conn)
    while indexer.run_once(conn, cfg):
        pass
    it = item(conn)
    assert it["summary"] and it["scopes"] == ["quokka"]
    distill.run_cycle(conn, cfg, client, now=LATER)
    assert len(client.calls) == 1


def test_new_message_makes_unit_pending_again(conn):
    src, cfg = setup(conn)
    client = StubClient()
    distill.run_cycle(conn, cfg, client, now=LATER)
    msg = SimpleNamespace(
        id=50,
        date=T0 + timedelta(minutes=10),
        message="ще одне повідомлення",
        edit_date=None,
        sender=None,
        sender_id=7,
        reply_to=None,
        reactions=None,
        media=None,
    )
    telegram.on_message(conn, src, CHAT, msg)
    while indexer.run_once(conn, cfg):
        pass
    assert item(conn)["summary"]  # stale summary kept until refreshed
    distill.run_cycle(conn, cfg, client, now=LATER)
    assert len(client.calls) == 2


def test_tiny_units_are_skipped(conn):
    _, cfg = setup(conn, text="ок")
    client = StubClient()
    assert distill.run_cycle(conn, cfg, client, now=LATER)["skipped"] == 1
    assert client.calls == []
    assert distill.pending(conn, cfg.llm, 10, now=LATER) == []


def test_big_backlog_goes_to_batch_and_applies(conn):
    _, cfg = setup(conn, n=4, batch_threshold=3)
    client = StubClient()
    stats = distill.run_cycle(conn, cfg, client, now=LATER)
    assert stats["batched"] == 4 and client.calls == []
    assert distill.pending(conn, cfg.llm, 10, now=LATER) == []  # in flight, not resent
    distill.run_cycle(conn, cfg, client, now=LATER)
    rows = conn.execute("SELECT summary, distill_batch FROM items WHERE NOT hidden").fetchall()
    assert len(rows) == 4 and all(r["summary"] and r["distill_batch"] is None for r in rows)
    usage = conn.execute("SELECT purpose, requests FROM llm_usage").fetchall()
    assert [(u["purpose"], u["requests"]) for u in usage] == [("distill_batch", 4)]


def test_daily_cap_stops_requests(conn):
    _, cfg = setup(conn, n=3, daily_token_cap=1500)
    client = StubClient()
    distill.run_cycle(conn, cfg, client, now=LATER)
    assert len(client.calls) <= 1  # each request ~1100 tokens: the cap allows at most one
    before = len(client.calls)
    distill.run_cycle(conn, cfg, client, now=LATER)
    assert len(client.calls) == before  # cap reached for today


def test_cost_estimate(conn):
    _, cfg = setup(conn, n=2)
    est = distill.cost_estimate(conn, cfg, now=LATER)
    assert est["units_to_send"] == 2 and est["mode"] == "live"
    assert est["model"] == "gpt-6-luna" and est["est_input_tokens"] > 0
    assert est["est_cost_usd_batch"] == pytest.approx(est["est_cost_usd_live"] / 2, abs=0.01)


def test_only_redacted_text_is_sent(conn):
    _, cfg = setup(conn, text="Your verification code is 482913. " + LONG)
    client = StubClient()
    distill.run_cycle(conn, cfg, client, now=LATER)
    assert client.calls and "482913" not in client.calls[0] and "[REDACTED:otp]" in client.calls[0]


def test_schema_is_strict_compatible():
    def check(node):
        if node.get("type") == "object":
            assert node["additionalProperties"] is False
            assert set(node["required"]) == set(node["properties"])
            for child in node["properties"].values():
                check(child)
        if node.get("type") == "array":
            check(node["items"])

    check(distill.SCHEMA)
    json.dumps(distill.SCHEMA)


@pytest.mark.slow
@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="needs OPENAI_API_KEY")
def test_live_openai_call_on_fixture(conn):
    _, cfg = setup(conn)
    stats = distill.run_cycle(conn, cfg, distill.OpenAIClient(), now=LATER)
    it = item(conn)
    assert stats["live"] == 1 and it["summary"] and it["language"] in ("uk", "mixed")


def test_disabled_by_default_and_needs_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    assert distill.default_client(Config()) is None
    monkeypatch.delenv("OPENAI_API_KEY")
    assert distill.default_client(Config(llm=LlmConfig(enabled=True))) is None


def test_sql_content_hash_matches_python(conn):
    setup(conn)
    it = item(conn)
    sql = conn.execute(
        "SELECT encode(sha256(convert_to("
        "coalesce(title, '') || E'\\n' || raw_text, 'UTF8')), 'hex') AS h FROM items WHERE id = %s",
        (it["id"],),
    ).fetchone()["h"]
    assert sql == it["content_hash"] == distill.content_hash(it["title"], it["raw_text"])


def test_items_without_hash_get_pending_after_backfill_migration(conn):
    from importlib import resources

    _, cfg = setup(conn)
    conn.execute("UPDATE items SET content_hash = NULL")
    assert distill.pending(conn, cfg.llm, 10, now=LATER) == []  # the bug
    conn.execute((resources.files("kb.migrations") / "0005_backfill_content_hash.sql").read_text())
    assert len(distill.pending(conn, cfg.llm, 10, now=LATER)) == 1
