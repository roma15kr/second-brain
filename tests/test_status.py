from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from kb import db, events, metrics
from kb.api import auth
from kb.api.app import build_app

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def brief(conn, days_ago, push=True):
    return conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode, push,"
        " created_at) VALUES ('morning', now(), now(), 'h', '[]', 'data', %s, %s) RETURNING id",
        (push, NOW - timedelta(days=days_ago)),
    ).fetchone()["id"]


def loop(conn, status, kind="i_owe", days_ago=3):
    conn.execute(
        "INSERT INTO loops (kind, title, status, created_at) VALUES (%s, 't', %s, %s)",
        (kind, status, NOW - timedelta(days=days_ago)),
    )


def test_usefulness_metric_28_days(conn):
    used = [brief(conn, d) for d in (1, 2, 3, 4)]
    brief(conn, 5)  # never opened
    brief(conn, 6, push=False)  # quiet revision pass: not counted
    old = brief(conn, 40)  # outside the window
    for i, b in enumerate(used):
        events.record(conn, "brief_opened" if i % 2 else "brief_rating", f"brief:{b}", {})
    events.record(conn, "brief_opened", f"brief:{old}", {})
    for status in ["done"] * 5 + ["dismissed"] * 2 + ["open"] * 3:
        loop(conn, status)
    loop(conn, "open", kind="manual")  # owner's own tasks are not detections
    loop(conn, "done", days_ago=60)
    m = metrics.usefulness(conn, NOW)
    assert m["briefs"] == {"total": 5, "used": 4, "share": 0.8, "target": 0.8}
    assert m["loops"] == {"total": 10, "resolved": 7, "share": 0.7, "target": 0.7}


def test_empty_metric_has_no_share(conn):
    m = metrics.usefulness(conn, NOW)
    assert m["briefs"]["share"] is None and m["loops"]["share"] is None


def test_status_api(conn, pg_url, config):
    conn.execute(
        "INSERT INTO routine_runs (routine, slot, status, delayed, error) VALUES"
        " ('morning', now(), 'failed', true, 'OpenAI timeout')"
    )
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    data = c.get("/api/status").json()
    assert data["routine_runs"][0]["error"] == "OpenAI timeout"
    assert data["ai"]["budget_usd"] == 30.0 and "sources" in data["system"]
    assert data["usefulness"]["days"] == 28
