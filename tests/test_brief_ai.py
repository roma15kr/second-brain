from datetime import datetime, timedelta

from kb.config import Config, LlmConfig
from kb.distill import Usage, month_spend_usd, record_usage
from kb.routines import KYIV, briefs, factpack
from tests.test_routines_brief import add_item

NOW = datetime(2026, 10, 20, 8, 0, tzinfo=KYIV)
EVENING = datetime(2026, 10, 19, 19, 0, tzinfo=KYIV)


class FakeLlm:
    def __init__(self, data=None, error=None, usage=None):
        self.data, self.error, self.calls = data, error, []
        self.usage = usage or Usage(10_000, 1_000)

    def structured(self, model, system, text, schema, name, effort):
        self.calls.append({"model": model, "system": system, "text": text, "name": name})
        if self.error:
            raise self.error
        return self.data, self.usage


def seed(conn):
    a = add_item(
        conn,
        "a",
        "email_thread",
        ["quokka"],
        EVENING + timedelta(hours=1),
        title="Listing price",
        summary="Dealer asks about the listing price.",
    )
    b = add_item(
        conn,
        "b",
        "tg_conversation",
        ["rdim"],
        EVENING + timedelta(hours=2),
        title="Customs",
        summary="Olena promises customs documents tomorrow.",
    )
    return a, b


def test_ai_brief_cites_pack_items_and_records_cost(conn):
    a, _ = seed(conn)
    llm = FakeLlm(
        {
            "sections": [
                {"title": "Quokka", "text": "A dealer needs a price.", "refs": [f"item:{a}"]}
            ],
            "focus": [{"ref": f"item:{a}", "reason": "Dealer is waiting"}],
        }
    )
    bid = briefs.run_morning(conn, NOW, llm, Config())
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None and brief["id"] == bid and brief["mode"] == "ai"
    kinds = [s["kind"] for s in brief["sections"]]
    assert kinds[:2] == ["focus", "ai"] and "data" in kinds  # full activity still listed
    assert brief["sections"][0]["items"][0]["reason"] == "Dealer is waiting"
    assert brief["cost_usd"] > 0
    # gpt-6.1-sol at $2 / $10 per 1M tokens: 10k in + 1k out = $0.03
    assert abs(brief["cost_usd"] - 0.03) < 1e-6
    assert llm.calls[0]["model"] == "gpt-6.1-sol"
    assert f"[item:{a}]" in llm.calls[0]["text"] and "Dealer asks" in llm.calls[0]["text"]
    assert month_spend_usd(conn, NOW.date()) > 0


def test_brief_refs_validated_unknown_ids_dropped(conn):
    a, _ = seed(conn)
    llm = FakeLlm(
        {
            "sections": [
                {"title": "Invented", "text": "A deal was signed.", "refs": ["item:999999"]},
                {
                    "title": "Mixed",
                    "text": "Dealer.",
                    "refs": ["item:999999", f"item:{a}", f"item:{a}"],
                },
            ],
            "focus": [{"ref": "item:424242", "reason": "made up"}],
        }
    )
    briefs.run_morning(conn, NOW, llm, Config())
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None
    titles = [s["title"] for s in brief["sections"]]
    assert "Invented" not in titles and "Focus" not in titles
    mixed = next(s for s in brief["sections"] if s["title"] == "Mixed")
    assert mixed["refs"] == [f"item:{a}"]


def test_data_only_brief_when_budget_reached(conn):
    seed(conn)
    record_usage(conn, "_routines", "gpt-6.1-sol", "morning", Usage(20_000_000, 0))  # $40
    llm = FakeLlm({"sections": [], "focus": []})
    briefs.run_morning(conn, NOW, llm, Config(llm=LlmConfig(monthly_budget_usd=30)))
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None and brief["mode"] == "data" and llm.calls == []
    assert brief["sections"][0]["title"] == "AI budget reached"
    assert brief["cost_usd"] == 0


def test_ai_failure_still_stores_data_brief(conn):
    seed(conn)
    briefs.run_morning(conn, NOW, FakeLlm(error=RuntimeError("timeout")), Config())
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None and brief["mode"] == "data"
    assert brief["sections"][0]["title"] == "AI unavailable"


def test_quiet_period_makes_no_ai_call(conn):
    llm = FakeLlm({"sections": [], "focus": []})
    briefs.run_morning(conn, NOW, llm, Config())
    assert llm.calls == []


def test_evening_wrap_covers_today_since_morning(conn):
    morning = datetime(2026, 10, 20, 8, 0, tzinfo=KYIV)
    today = add_item(conn, "t", "email_thread", ["digisoft"], morning + timedelta(hours=3))
    add_item(conn, "y", "email_thread", ["digisoft"], morning - timedelta(minutes=5))
    llm = FakeLlm({"sections": [], "focus": []})
    briefs.run_evening(conn, datetime(2026, 10, 20, 19, 0, tzinfo=KYIV), llm, Config())
    brief = briefs.latest(conn, ["evening"])
    assert brief is not None and brief["headline"].startswith("Evening wrap: 1 conversation")
    assert [i["id"] for s in brief["sections"] for i in s["items"]] == [today]
    assert "EVENING wrap" in llm.calls[0]["system"]
    assert factpack.evening_window(datetime(2026, 10, 20, 19, 0, tzinfo=KYIV))[0] == morning


def test_morning_lists_coming_up_routines(conn):
    briefs.run_morning(conn, NOW, None, Config())
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None
    up = next(s for s in brief["sections"] if s["title"] == "Coming up")
    assert up["text"] == "Mail revision 11:00, 14:00, 17:00 · Evening wrap 19:00"


def test_scheduler_runs_morning_and_evening():
    assert set(briefs.runners(Config(), None)) == {"morning", "evening", "revision"}
