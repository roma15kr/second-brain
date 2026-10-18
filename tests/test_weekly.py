from datetime import UTC, date, datetime, timedelta

from fastapi.testclient import TestClient

from kb import db
from kb.api import auth
from kb.api.app import build_app
from kb.config import Config
from kb.routines import KYIV, briefs, weekly
from tests.test_brief_ai import FakeLlm
from tests.test_routines_brief import add_item

MONDAY = datetime(2026, 10, 26, 8, 0, tzinfo=KYIV)
FRIDAY = datetime(2026, 10, 23, 19, 0, tzinfo=KYIV)
CSRF = {"X-KB-Request": "1"}


def test_windows():
    assert weekly.review_window(FRIDAY)[0] == datetime(2026, 10, 19, 0, 0, tzinfo=KYIV)
    start, end = weekly.plan_window(MONDAY)
    assert start == datetime(2026, 10, 19, 0, 0, tzinfo=KYIV)
    assert end == datetime(2026, 10, 26, 0, 0, tzinfo=KYIV)


def test_weekly_review_has_scope_sections_numbers_and_aging_loops(conn):
    a = add_item(conn, "a", "email_thread", ["quokka"], FRIDAY - timedelta(days=2), title="Listing")
    conn.execute("UPDATE items SET outcome = 'Agreed 12% commission', participants = '{Олена}'")
    conn.execute(
        "INSERT INTO loops (kind, title, counterpart, opened_at, created_at)"
        " VALUES ('i_owe', 'Send deck', 'Максим', %s, %s)",
        (FRIDAY - timedelta(days=10), FRIDAY - timedelta(days=10)),
    )
    llm = FakeLlm(
        {
            "sections": [{"title": "Quokka", "text": "Commission agreed.", "refs": [f"item:{a}"]}],
            "focus": [],
        }
    )
    weekly.run_review(conn, FRIDAY, llm, Config())
    brief = briefs.latest(conn, ["weekly_review"])
    assert brief is not None and brief["mode"] == "ai"
    titles = [s["title"] for s in brief["sections"]]
    assert titles[:2] == ["Quokka", "This week in numbers"]
    numbers = brief["sections"][1]["text"]
    assert "1 email threads" in numbers and "1 decisions" in numbers and "Олена (1)" in numbers
    aging = next(s for s in brief["sections"] if s["title"] == "Open loops by age")
    assert aging["items"][0]["title"] == "Send deck"
    assert "WEEKLY REVIEW" in llm.calls[0]["system"]


def plan_llm(item_id, extra=0):
    priorities = [
        {"title": f"Priority {n}", "reason": "r", "refs": [f"item:{item_id}"]}
        for n in range(6 + extra)
    ]
    priorities.append({"title": "Invented", "reason": "x", "refs": ["item:999999"]})
    return FakeLlm({"sections": [], "priorities": priorities})


def test_plan_proposes_at_most_five_sourced_priorities(conn):
    a = add_item(conn, "a", "email_thread", ["rdim"], MONDAY - timedelta(days=3))
    bid = weekly.run_plan(conn, MONDAY, plan_llm(a), Config())
    plan = conn.execute("SELECT * FROM weekly_plans WHERE brief_id = %s", (bid,)).fetchone()
    assert plan["week_start"] == date(2026, 10, 26)
    assert [p["title"] for p in plan["proposed"]] == [f"Priority {n}" for n in range(5)]
    assert all(p["refs"] == [f"item:{a}"] for p in plan["proposed"])


def test_weekly_plan_accept_feeds_morning_brief(conn):
    a = add_item(conn, "a", "email_thread", ["rdim"], MONDAY - timedelta(days=3))
    bid = weekly.run_plan(conn, MONDAY, plan_llm(a), Config())
    weekly.accept_plan(conn, bid, MONDAY + timedelta(minutes=5))
    tuesday = MONDAY + timedelta(days=1)
    add_item(conn, "b", "email_thread", ["rdim"], tuesday - timedelta(hours=3))
    llm = FakeLlm({"sections": [], "focus": []})
    briefs.run_morning(conn, tuesday, llm, Config())
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None
    prio = next(s for s in brief["sections"] if s["title"] == "This week's priorities")
    assert prio["text"].startswith("1. Priority 0")
    assert "This week's priorities (accepted by the owner)" in llm.calls[0]["text"]
    # next week: no priorities carried over
    assert weekly.accepted_priorities(conn, MONDAY + timedelta(days=7)) == []


def test_edited_plan_is_marked(conn):
    a = add_item(conn, "a", "email_thread", ["rdim"], MONDAY - timedelta(days=3))
    bid = weekly.run_plan(conn, MONDAY, plan_llm(a), Config())
    weekly.accept_plan(
        conn, bid, MONDAY, [{"title": "Close the Epicentr deal", "reason": "", "refs": []}]
    )
    plan = conn.execute("SELECT accepted, edited FROM weekly_plans").fetchone()
    assert plan["edited"] is True and plan["accepted"][0]["title"] == "Close the Epicentr deal"


def test_week_api_shows_review_and_plan_and_accepts(conn, pg_url):
    a = add_item(conn, "a", "email_thread", ["rdim"], MONDAY - timedelta(days=3))
    weekly.run_review(conn, FRIDAY, None, Config())
    conn.execute("UPDATE briefs SET created_at = %s WHERE routine = 'weekly_review'", (FRIDAY,))
    bid = weekly.run_plan(conn, MONDAY, plan_llm(a), Config())
    app = build_app(None, connect=lambda: db.connect(pg_url), rp=auth.RelyingParty("https://os.x"))
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    last = c.get("/api/week", params={"start": "2026-10-21"}).json()  # any day of that week
    assert last["week_start"] == "2026-10-19" and last["review"]["routine"] == "weekly_review"
    this = c.get("/api/week", params={"start": "2026-10-26"}).json()
    assert this["plan"]["brief"]["id"] == bid and this["plan"]["accepted"] is None
    assert c.post(f"/api/week/plan/{bid}/accept", json={}, headers=CSRF).status_code == 200
    assert len(c.get("/api/week", params={"start": "2026-10-26"}).json()["plan"]["accepted"]) == 5
    assert c.post("/api/week/plan/99999/accept", json={}, headers=CSRF).status_code == 404


def test_scheduler_has_weekly_runners():
    assert {"weekly_review", "weekly_plan"} <= set(briefs.runners(Config(), None))
