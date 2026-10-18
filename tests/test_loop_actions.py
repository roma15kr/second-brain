from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kb import db, loops
from kb.api import auth
from kb.api.app import build_app
from kb.config import Config
from kb.routines import KYIV, briefs
from tests.test_brief_ai import FakeLlm

CSRF = {"X-KB-Request": "1"}
# Thursday 22 Oct 2026 08:00 Kyiv
NOW = datetime(2026, 10, 22, 8, 0, tzinfo=KYIV)


def add(
    conn,
    kind="owed_to_me",
    title="Customs documents",
    due=None,
    who="Олена",
    scopes=("quokka",),
    opened=None,
):
    return conn.execute(
        "INSERT INTO loops (kind, title, counterpart, scopes, due_date, opened_at, created_at,"
        " source_message_key, source_link) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,"
        " 'https://t.me/c/1/2') RETURNING id",
        (
            kind,
            title,
            who,
            list(scopes),
            due,
            opened or NOW - timedelta(days=3),
            opened or NOW,
            f"k-{title}",
        ),
    ).fetchone()["id"]


def test_overdue_marked(conn):
    add(conn, due=date(2026, 10, 21))
    add(
        conn,
        kind="i_owe",
        title="Send price list",
        due=date(2026, 10, 22),
        who="Вячеслав",
        scopes=("rdim",),
    )
    add(conn, kind="manual", title="Renew domain")
    rows = {r["title"]: r for r in loops.list_loops(conn, NOW)}
    assert rows["Customs documents"]["overdue"] is True
    assert (
        rows["Send price list"]["due_today"] is True and rows["Send price list"]["overdue"] is False
    )
    assert rows["Renew domain"]["age_days"] == 3 and rows["Renew domain"]["due_date"] is None
    assert [r["title"] for r in loops.list_loops(conn, NOW)][:2] == [
        "Customs documents",
        "Send price list",
    ]


def test_snooze_returns_on_date(conn):
    lid = add(conn)
    with pytest.raises(loops.LoopError):
        loops.act(conn, lid, "snooze", NOW, until=date(2026, 10, 22))  # not in the future
    loops.act(conn, lid, "snooze", NOW, until=date(2026, 10, 24))
    assert loops.list_loops(conn, NOW) == []  # hidden from open loops
    assert loops.wake_snoozed(conn, NOW + timedelta(days=1)) == 0  # Friday: still snoozed
    assert loops.wake_snoozed(conn, NOW + timedelta(days=2)) == 1  # Saturday 24th: back
    assert [r["id"] for r in loops.list_loops(conn, NOW + timedelta(days=2))] == [lid]


def test_dismiss_records_source_and_event(conn):
    lid = add(conn)
    loops.act(conn, lid, "dismiss", NOW)
    assert conn.execute("SELECT source_message_key FROM loop_dismissed_sources").fetchone() == {
        "source_message_key": "k-Customs documents"
    }
    events = [(r["action"], r["by"]) for r in conn.execute("SELECT action, by FROM loop_events")]
    assert events == [("dismiss", "owner")]
    assert conn.execute("SELECT kind FROM app_events").fetchone()["kind"] == "loop_dismissed"


def test_filters_direction_scope_person(conn):
    add(conn, kind="i_owe", title="Send price list", who="Вячеслав", scopes=("rdim",))
    add(conn, kind="i_owe", title="Send deck", who="Олена", scopes=("quokka",))
    add(conn, kind="owed_to_me", title="Invoice", who="Вячеслав", scopes=("rdim",))
    titles = [r["title"] for r in loops.list_loops(conn, NOW, kind="i_owe", scope="rdim")]
    assert titles == ["Send price list"]
    assert {r["title"] for r in loops.list_loops(conn, NOW, person="вячеслав")} == {
        "Send price list",
        "Invoice",
    }


def test_morning_brief_lists_overdue_promise(conn):
    add(conn, due=date(2026, 10, 21))
    briefs.run_morning(conn, NOW, None, Config())
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None
    assert brief["headline"] == "Morning brief: 1 due"
    due = next(s for s in brief["sections"] if s["title"] == "Due today & overdue")
    assert due["items"][0]["title"] == "Customs documents"
    assert due["items"][0]["summary"] == "Owed to you by Олена · overdue since 2026-10-21"


def test_ai_may_cite_loops(conn):
    lid = add(conn, due=date(2026, 10, 21))
    llm = FakeLlm(
        {
            "sections": [{"title": "Chase", "text": "Ask Olena.", "refs": [f"loop:{lid}"]}],
            "focus": [],
        }
    )
    briefs.run_morning(conn, NOW, llm, Config())
    assert f"[loop:{lid}]" in llm.calls[0]["text"]
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None
    assert next(s for s in brief["sections"] if s["title"] == "Chase")["refs"] == [f"loop:{lid}"]


def test_evening_wrap_lists_closed_and_new(conn):
    done = add(conn, kind="i_owe", title="Send deck", opened=NOW)
    add(
        conn,
        kind="i_owe",
        title="New promise",
        due=date(2026, 10, 26),
        opened=NOW + timedelta(hours=5),
    )
    loops.act(conn, done, "done", NOW + timedelta(hours=6))
    evening = datetime(2026, 10, 22, 19, 0, tzinfo=KYIV)
    briefs.run_evening(conn, evening, None, Config())
    brief = briefs.latest(conn, ["evening"])
    assert brief is not None
    by_title = {s["title"]: [i["title"] for i in s["items"]] for s in brief["sections"]}
    assert by_title["Closed today"] == ["Send deck"]
    assert "New promise" in by_title["Opened today"]


@pytest.fixture
def client(conn, pg_url):
    app = build_app(None, connect=lambda: db.connect(pg_url), rp=auth.RelyingParty("https://os.x"))
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def test_loops_api(client, conn):
    r = client.post(
        "/api/loops", json={"title": "Renew zhukovsky.biz", "scope": "personal"}, headers=CSRF
    )
    lid = r.json()["id"]
    data = client.get("/api/loops").json()
    assert [lp["id"] for lp in data["loops"]] == [lid] and data["open_counts"] == {"manual": 1}
    due = (datetime.now(UTC) + timedelta(days=3)).date().isoformat()
    assert (
        client.post(
            f"/api/loops/{lid}/act", json={"action": "due", "due": due}, headers=CSRF
        ).status_code
        == 200
    )
    assert client.get("/api/loops").json()["loops"][0]["due_date"] == due
    assert (
        client.post(f"/api/loops/{lid}/act", json={"action": "done"}, headers=CSRF).status_code
        == 200
    )
    assert client.get("/api/loops").json()["loops"] == []
    assert [
        lp["id"] for lp in client.get("/api/loops", params={"status": "done"}).json()["loops"]
    ] == [lid]
    assert (
        client.post("/api/loops/999/act", json={"action": "done"}, headers=CSRF).status_code == 404
    )
    assert client.post("/api/loops", json={"title": " "}, headers=CSRF).status_code == 400
