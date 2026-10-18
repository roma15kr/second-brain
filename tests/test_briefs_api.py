from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from kb import db, events
from kb.api import auth
from kb.api.app import build_app

CSRF = {"X-KB-Request": "1"}


@pytest.fixture
def client(conn, pg_url):
    app = build_app(None, connect=lambda: db.connect(pg_url), rp=auth.RelyingParty("https://os.x"))
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def add_brief(conn, routine="morning", headline="Morning brief: 2 conversations across 2 scopes"):
    return conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
        " VALUES (%s, now(), now(), %s, '[]', 'data') RETURNING id",
        (routine, headline),
    ).fetchone()["id"]


def test_list_filters_by_type_and_shows_opened_state(client, conn):
    m = add_brief(conn)
    e = add_brief(conn, "evening", "Evening wrap: nothing new")
    events.record(conn, "brief_opened", f"brief:{m}", {"via": "app"})
    data = client.get("/api/briefs").json()
    assert [b["id"] for b in data["briefs"]] == [e, m]
    assert {b["id"]: b["opened"] for b in data["briefs"]} == {e: False, m: True}
    only = client.get("/api/briefs", params={"routine": "evening"}).json()["briefs"]
    assert [b["id"] for b in only] == [e]


def test_list_pages_by_id(client, conn):
    ids = [add_brief(conn) for _ in range(32)]
    first = client.get("/api/briefs").json()
    assert len(first["briefs"]) == 30 and first["next_before"] == ids[2]
    rest = client.get("/api/briefs", params={"before": first["next_before"]}).json()
    assert [b["id"] for b in rest["briefs"]] == [ids[1], ids[0]] and rest["next_before"] is None


def test_opening_from_push_is_recorded(client, conn):
    bid = add_brief(conn)
    assert client.get(f"/api/briefs/{bid}").json()["opened"] is False
    r = client.post(f"/api/briefs/{bid}/opened", json={"via": "push"}, headers=CSRF)
    assert r.status_code == 200
    row = conn.execute("SELECT kind, ref, value FROM app_events").fetchone()
    assert row == {"kind": "brief_opened", "ref": f"brief:{bid}", "value": {"via": "push"}}
    assert client.get(f"/api/briefs/{bid}").json()["opened"] is True


def test_rating_latest_wins(client, conn):
    bid = add_brief(conn)
    client.post(f"/api/briefs/{bid}/rating", json={"useful": False}, headers=CSRF)
    client.post(f"/api/briefs/{bid}/rating", json={"useful": True}, headers=CSRF)
    assert client.get(f"/api/briefs/{bid}").json()["useful"] is True


def test_unknown_brief_is_404(client):
    assert client.get("/api/briefs/999").status_code == 404


def test_unknown_event_kind_rejected(conn):
    with pytest.raises(ValueError, match="unknown event kind"):
        events.record(conn, "clicked_ad", "x")
