from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from kb import db, people
from kb.api import auth
from kb.api.app import build_app

CSRF = {"X-KB-Request": "1"}
NOW = datetime.now(UTC)


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


def item(conn, key, keys, scopes, ago_hours, outcome=None, participants=()):
    return conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,"
        " last_activity_at, occurred_at, identity_keys, outcome, participants)"
        " VALUES ('s', %s, 'email_thread', %s, %s, 'x', %s, %s, %s, %s, %s) RETURNING id",
        (
            key,
            list(scopes),
            f"Thread {key}",
            NOW - timedelta(hours=ago_hours),
            NOW - timedelta(hours=ago_hours),
            list(keys),
            outcome,
            list(participants),
        ),
    ).fetchone()["id"]


@pytest.fixture
def hostinger(conn):
    a = people.register(conn, ["email:billing@hostinger.example"], "Hostinger")
    b = people.register(conn, ["email:support@hostinger.example"], "Hostinger Support")
    me = people.register(conn, ["email:me@example.com"], "Me")
    item(conn, "a", ["email:billing@hostinger.example", "email:me@example.com"], ["digisoft"], 1)
    item(conn, "b", ["email:support@hostinger.example"], ["personal"], 30)
    return a, b, me


def test_people_by_recent_activity_without_owner(client, hostinger):
    a, b, _ = hostinger
    rows = client.get("/api/people").json()["people"]
    assert [r["id"] for r in rows] == [a, b]  # owner excluded, newest first
    assert rows[0]["channels"] == ["email"] and rows[0]["scopes"] == ["digisoft"]


def test_people_search_for_palette(client, hostinger):
    a, b, _ = hostinger
    assert {
        p["id"] for p in client.get("/api/people", params={"q": "hosting"}).json()["people"]
    } == {a, b}


def test_merge_from_the_ui_and_undo(client, conn, hostinger):
    a, b, _ = hostinger
    r = client.post(f"/api/people/{a}/merge", json={"other_id": b}, headers=CSRF)
    merge_id = r.json()["merge_id"]
    prof = client.get(f"/api/people/{a}").json()
    assert set(prof["identities"]) == {
        "email:billing@hostinger.example",
        "email:support@hostinger.example",
    }
    assert prof["scopes"] == ["digisoft", "personal"]
    assert [p["id"] for p in client.get("/api/people").json()["people"]] == [a]
    assert client.post(f"/api/people/merges/{merge_id}/undo", headers=CSRF).status_code == 200
    assert client.get(f"/api/people/{b}").json()["identities"] == [
        "email:support@hostinger.example"
    ]
    assert (
        client.post(f"/api/people/{a}/merge", json={"other_id": a}, headers=CSRF).status_code == 400
    )


def test_person_shows_open_loops_with_them(client, conn, hostinger):
    a, _, _ = hostinger
    conn.execute(
        "INSERT INTO loops (kind, title, counterpart) VALUES ('owed_to_me', 'Invoice', 'Hostinger')"
    )
    assert [lp["title"] for lp in client.get(f"/api/people/{a}").json()["open_loops"]] == [
        "Invoice"
    ]
    assert client.get("/api/people/999999").status_code == 404


def test_link_identity_validates(client, hostinger):
    a, _, _ = hostinger
    assert (
        client.post(f"/api/people/{a}/link", json={"key": "nonsense"}, headers=CSRF).status_code
        == 400
    )
    assert (
        client.post(
            f"/api/people/{a}/link", json={"key": "phone:+380501234567"}, headers=CSRF
        ).status_code
        == 200
    )


def test_scope_page_and_archive(client, conn):
    item(conn, "d", [], ["rdim"], 2, outcome="Dealer terms agreed", participants=["Вячеслав"])
    conn.execute(
        "INSERT INTO loops (kind, title, scopes) VALUES ('i_owe', 'Send price list', '{rdim}')"
    )
    page = client.get("/api/scopes/rdim").json()
    assert page["archived"] is False and page["decisions"][0]["outcome"] == "Dealer terms agreed"
    assert page["key_people"] == [{"name": "Вячеслав", "conversations": 1}]
    assert [lp["title"] for lp in page["open_loops"]] == ["Send price list"]
    assert sum(a["n"] for a in page["activity"]) == 1
    assert (
        client.post("/api/scopes/rdim/archive", json={"archived": True}, headers=CSRF).status_code
        == 200
    )
    assert client.get("/api/scopes/rdim").json()["archived"] is True
    assert client.get("/api/scopes/acme").status_code == 404
