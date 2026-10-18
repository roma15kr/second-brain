import argparse
import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from kb import cli, db, scopes, secrets
from kb.api import auth
from kb.api.app import build_app
from kb.connectors import accounts, imap
from tests.fakes import FakeImap, make_email

CSRF = {"X-KB-Request": "1"}
PASSWORD = "abcd efgh ijkl mnop"
NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("KB_SECRET_KEY", "a-long-test-passphrase-for-the-secret-key")
    accounts._invalidate()


@pytest.fixture
def logins(monkeypatch):
    seen = []
    monkeypatch.setattr(accounts, "check_imap", lambda *a: seen.append(("imap", *a)))
    monkeypatch.setattr(accounts, "check_smtp", lambda *a: seen.append(("smtp", *a)))
    return seen


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


def test_secret_roundtrip_and_wrong_key(monkeypatch):
    blob = secrets.seal({"password": PASSWORD})
    assert PASSWORD.encode() not in blob
    assert secrets.unseal(blob) == {"password": PASSWORD}
    monkeypatch.setenv("KB_SECRET_KEY", "a-different-passphrase-entirely")
    with pytest.raises(secrets.SecretsError, match="cannot decrypt"):
        secrets.unseal(blob)
    monkeypatch.delenv("KB_SECRET_KEY")
    with pytest.raises(secrets.SecretsError, match="KB_SECRET_KEY"):
        secrets.seal({})


def test_secret_roundtrip_and_never_returned_by_api(client, conn, logins):
    r = client.post(
        "/api/connectors/mail",
        json={
            "mailbox": {
                "preset": "gmail",
                "address": "Me@Personal.example",
                "password": PASSWORD,
                "scopes": ["personal"],
            }
        },
        headers=CSRF,
    )
    assert r.status_code == 200
    # Gmail preset: both servers checked with the same app password
    assert logins == [
        ("imap", "imap.gmail.com", 993, "Me@Personal.example", PASSWORD),
        ("smtp", "smtp.gmail.com", 465, "ssl", "Me@Personal.example", PASSWORD),
    ]
    listing = client.get("/api/connectors/mail").json()
    assert PASSWORD not in json.dumps(listing)
    [m] = listing["mailboxes"]
    assert (
        m["password_set"] is True
        and m["address"] == "me@personal.example"
        and m["scopes"] == ["personal"]
    )
    raw = conn.execute("SELECT settings::text AS s, secret FROM connector_accounts").fetchone()
    assert PASSWORD not in raw["s"] and PASSWORD.encode() not in bytes(raw["secret"])


def test_wrong_imap_password_not_saved(client, conn, monkeypatch):
    def refuse(*a):
        raise accounts.ConnectorError("IMAP login to imap.gmail.com failed: [AUTHENTICATIONFAILED]")

    monkeypatch.setattr(accounts, "check_imap", refuse)
    r = client.post(
        "/api/connectors/mail",
        json={"mailbox": {"address": "me@example.org", "password": "wrong"}},
        headers=CSRF,
    )
    assert r.status_code == 400 and "AUTHENTICATIONFAILED" in r.json()["detail"]
    assert conn.execute("SELECT count(*) AS n FROM connector_accounts").fetchone()["n"] == 0


def test_own_domain_needs_both_servers_and_checks_both(client, logins):
    body: dict[str, object] = {
        "preset": "imap",
        "address": "info@digisoft.example",
        "password": PASSWORD,
    }
    assert (
        client.post("/api/connectors/mail", json={"mailbox": body}, headers=CSRF).status_code == 400
    )
    body |= {
        "imap_host": "mail.digisoft.example",
        "smtp_host": "mail.digisoft.example",
        "smtp_port": 587,
        "smtp_security": "starttls",
        "smtp_username": "info",
        "smtp_password": "other",
    }
    assert (
        client.post("/api/connectors/mail", json={"mailbox": body}, headers=CSRF).status_code == 200
    )
    assert logins[-1] == ("smtp", "mail.digisoft.example", 587, "starttls", "info", "other")
    dup = client.post("/api/connectors/mail", json={"mailbox": body}, headers=CSRF)
    assert dup.status_code == 400 and "already connected" in dup.json()["detail"]


def test_add_project_scope(client, conn, logins):
    r = client.post("/api/projects", json={"name": "Acme", "label": "ACME Corp"}, headers=CSRF)
    assert r.json() == {"name": "acme"}
    assert "acme" in [p["name"] for p in client.get("/api/projects").json()["projects"]]
    assert client.post("/api/projects", json={"name": "acme"}, headers=CSRF).status_code == 400
    assert client.post("/api/projects", json={"name": "Bad Name!"}, headers=CSRF).status_code == 400
    # usable to mark mailboxes, in rules and as a search filter
    body = {"address": "a@acme.example", "password": PASSWORD, "scopes": ["acme"]}
    assert (
        client.post("/api/connectors/mail", json={"mailbox": body}, headers=CSRF).status_code == 200
    )
    rule = client.post(
        "/api/settings/rules",
        json={"kind": "domain", "value": "acme.example", "scopes": ["acme"]},
        headers=CSRF,
    )
    assert rule.status_code == 200
    assert client.get("/api/search", params={"q": "x", "scope": "acme"}).status_code == 200
    assert scopes.known(conn)[-1] == "acme"
    assert (
        client.patch("/api/projects/acme", json={"label": "Acme"}, headers=CSRF).status_code == 200
    )


def test_new_account_ingested_without_restart(pg_url, conn, monkeypatch, logins):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("KB_CONFIG_YAML", "sources: []")
    accounts.add_mailbox(
        conn,
        accounts.Mailbox(
            label="Personal", address="me@personal.example", password=PASSWORD, scopes=("personal",)
        ),
        scopes.known(conn),
        NOW,
    )
    server = FakeImap()
    server.add(
        1,
        make_email("Dentist", "Your appointment is on Friday"),
        datetime(2026, 10, 19, tzinfo=UTC),
    )
    opened = []

    def open_client(source):
        opened.append((source.id, source.username(), source.password()))
        return server

    monkeypatch.setattr(imap, "open_client", open_client)
    cli.cmd_ingest(argparse.Namespace(once=True))
    assert opened == [("mail-1", "me@personal.example", PASSWORD)]
    assert (
        conn.execute("SELECT count(*) AS n FROM raw_records WHERE source_id = 'mail-1'").fetchone()[
            "n"
        ]
        == 1
    )


def test_connected_mailbox_scopes_and_owner_address(conn, config, logins):
    from kb import loops

    accounts.add_mailbox(
        conn,
        accounts.Mailbox(
            label="P", address="me@personal.example", password=PASSWORD, scopes=("personal",)
        ),
        scopes.known(conn),
        NOW,
    )
    source = accounts.effective_config(conn, config).source("mail-1")
    assert list(source.scopes) == ["personal"]
    assert "me@personal.example" in loops.owner_emails(conn, config)


def test_replace_password_rechecks(client, conn, logins, monkeypatch):
    body = {"address": "me@example.org", "password": PASSWORD}
    mid = client.post("/api/connectors/mail", json={"mailbox": body}, headers=CSRF).json()["id"]

    def refuse(*a):
        raise accounts.ConnectorError("IMAP login failed")

    monkeypatch.setattr(accounts, "check_imap", refuse)
    assert (
        client.patch(
            f"/api/connectors/mail/{mid}", json={"password": "new"}, headers=CSRF
        ).status_code
        == 400
    )
    assert (
        client.patch(
            f"/api/connectors/mail/{mid}", json={"scopes": ["rdim"]}, headers=CSRF
        ).status_code
        == 200
    )
    assert client.get("/api/connectors/mail").json()["mailboxes"][0]["scopes"] == ["rdim"]
