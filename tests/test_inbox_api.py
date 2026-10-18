from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kb import db
from kb.api import auth
from kb.api.app import build_app
from kb.routines import triage
from tests.test_triage import NOW, TriageLlm, mail

CSRF = {"X-KB-Request": "1"}


@pytest.fixture
def client(conn, pg_url, config):
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


@pytest.fixture
def triaged(conn, config):
    q = mail(
        conn,
        "q",
        "Olga <olga@dealer.example>",
        "Terms",
        "Can you confirm?",
        NOW - timedelta(hours=1),
    )
    n = mail(conn, "n", "news@shop.example", "Newsletter", "Sale", NOW - timedelta(hours=2))
    triage.run_pass(conn, NOW, TriageLlm(), config)
    return q, n


def test_inbox_groups_latest_pass(client, triaged):
    q, n = triaged
    data = client.get("/api/inbox").json()
    assert data["pass"]["headline"] == "Mail revision: 1 needs your reply"
    assert [i["item_id"] for i in data["groups"]["needs_reply"]] == [q]
    assert data["groups"]["needs_reply"][0]["action"] == "Answer Olga"
    assert data["groups"]["needs_reply"][0]["sender"] == "olga@dealer.example"
    assert [i["item_id"] for i in data["groups"]["noise"]] == [n]


def test_done_removes_from_needs_reply(client, triaged):
    q, _ = triaged
    assert client.post(f"/api/inbox/{q}/done", headers=CSRF).status_code == 200
    assert client.get("/api/inbox").json()["groups"]["needs_reply"] == []


def test_snooze_hides_until_time(client, conn, triaged):
    q, _ = triaged
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    assert (
        client.post(f"/api/inbox/{q}/snooze", json={"until": past}, headers=CSRF).status_code == 400
    )
    soon = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert (
        client.post(f"/api/inbox/{q}/snooze", json={"until": soon}, headers=CSRF).status_code == 200
    )
    assert client.get("/api/inbox").json()["groups"]["needs_reply"] == []
    conn.execute("UPDATE triage SET snoozed_until = now() - interval '1 minute'")
    assert len(client.get("/api/inbox").json()["groups"]["needs_reply"]) == 1


def test_sender_pref_from_inbox_applies_to_next_pass(client, conn, config, triaged):
    r = client.post(
        "/api/senders/pref", json={"address": "news@shop.example", "pref": "noise"}, headers=CSRF
    )
    assert r.status_code == 200
    assert triage.sender_prefs(conn, ["news@shop.example"]) == {"news@shop.example": "noise"}
    r = client.post(
        "/api/senders/pref", json={"address": "news@shop.example", "pref": None}, headers=CSRF
    )
    assert r.status_code == 200, r.text
    assert triage.sender_prefs(conn, ["news@shop.example"]) == {}


def test_change_scope_validates(client, triaged):
    q, _ = triaged
    r = client.post(f"/api/inbox/{q}/scope", json={"scope": "acme"}, headers=CSRF)
    assert r.status_code == 400 and "valid scopes" in r.json()["detail"]


def test_unknown_item_is_404(client):
    assert client.post("/api/inbox/424242/done", headers=CSRF).status_code == 404


def test_empty_inbox(client):
    assert client.get("/api/inbox").json()["pass"] is None
