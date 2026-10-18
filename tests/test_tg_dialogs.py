import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from kb import db, secrets, telegram_auth
from kb.api import auth
from kb.api.app import build_app
from kb.connectors import telegram, tg_dialogs
from kb.connectors.telegram import ChatInfo
from tests.test_telegram import ALLOWED, DM, OTHER, index_all, msg

CSRF = {"X-KB-Request": "1"}
NEW = ChatInfo(chat_id=-1004444, title="Quokka · Marketplaces", username=None, peer_type="channel")


def listed(conn, tg_source):
    when = datetime(2026, 10, 20, tzinfo=UTC)
    return tg_dialogs.upsert_dialogs(conn, tg_source, [(ALLOWED, when), (NEW, when), (DM, when)])


def test_config_allowlist_imported_once(conn, tg_source):
    assert listed(conn, tg_source) == 3
    data = tg_dialogs.listing(conn)
    assert {d["chat_id"] for d in data["included"]} == {ALLOWED.chat_id, DM.chat_id}
    assert [d["chat_id"] for d in data["to_mark"]] == [NEW.chat_id]
    assert data["included"][0]["scopes"] in (["quokka"], [])
    # the owner ignores a configured chat; a later listing does not include it again
    conn.execute("UPDATE tg_dialogs SET included = false WHERE chat_id = %s", (ALLOWED.chat_id,))
    assert listed(conn, tg_source) == 0
    eff = tg_dialogs.effective_source(conn, tg_source)
    assert eff.chat_config(ALLOWED.chat_id, None) is None


def test_new_dialog_not_ingested_until_included(conn, tg_source, tg_config):
    listed(conn, tg_source)
    eff = tg_dialogs.effective_source(conn, tg_source)
    assert telegram.on_message(conn, eff, NEW, msg(1, "price list for Rozetka")) is False
    assert conn.execute("SELECT count(*) AS n FROM raw_records").fetchone()["n"] == 0
    tg_dialogs.set_dialog(conn, tg_config, NEW.chat_id, included=True)
    eff = tg_dialogs.effective_source(conn, tg_source)
    assert telegram.on_message(conn, eff, NEW, msg(1, "price list for Rozetka")) is True
    assert telegram.on_message(conn, eff, OTHER, msg(2, "secret")) is False  # never listed


def test_mark_change_rescopes_items(conn, tg_source, tg_config):
    listed(conn, tg_source)
    tg_dialogs.set_dialog(conn, tg_config, NEW.chat_id, included=True)
    eff = tg_dialogs.effective_source(conn, tg_source)
    telegram.on_message(conn, eff, NEW, msg(1, "commission for the marketplace"))
    index_all(conn, tg_config)
    item = conn.execute("SELECT id, scopes FROM items WHERE kind = 'tg_conversation'").fetchone()
    assert item["scopes"] == ["personal"]  # source default before marking
    changed = tg_dialogs.set_dialog(conn, tg_config, NEW.chat_id, marks=["quokka"])
    assert changed == 1
    assert conn.execute("SELECT scopes FROM items WHERE id = %s", (item["id"],)).fetchone()[
        "scopes"
    ] == ["quokka"]
    tg_dialogs.set_dialog(conn, tg_config, NEW.chat_id, marks=["rdim"])
    assert conn.execute("SELECT scopes FROM items WHERE id = %s", (item["id"],)).fetchone()[
        "scopes"
    ] == ["rdim"]


@pytest.fixture
def client(conn, pg_url, tg_config, monkeypatch):
    monkeypatch.setenv("KB_SECRET_KEY", "a-long-test-passphrase-for-the-secret-key")
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=tg_config,
    )
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def test_dialog_api(client, conn, tg_source):
    listed(conn, tg_source)
    data = client.get("/api/connectors/telegram").json()
    assert [d["title"] for d in data["to_mark"]] == ["Quokka · Marketplaces"]
    r = client.post(
        f"/api/connectors/telegram/dialogs/{NEW.chat_id}",
        json={"included": True, "scopes": ["quokka"]},
        headers=CSRF,
    )
    assert r.status_code == 200
    data = client.get("/api/connectors/telegram").json()
    assert data["to_mark"] == [] and NEW.chat_id in {d["chat_id"] for d in data["included"]}
    bad = client.post(
        f"/api/connectors/telegram/dialogs/{NEW.chat_id}", json={"scopes": ["acme"]}, headers=CSRF
    )
    assert bad.status_code == 400
    assert (
        client.post(
            "/api/connectors/telegram/dialogs/1", json={"included": True}, headers=CSRF
        ).status_code
        == 404
    )


class FakeQr:
    url = "tg://login?token=abc"

    def __init__(self, outcome):
        self.outcome = outcome

    async def wait(self, timeout):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class FakeTelegram:
    def __init__(self, outcome):
        self.outcome, self.passwords = outcome, []

    async def qr_login(self):
        return FakeQr(self.outcome)

    async def sign_in(self, password):
        self.passwords.append(password)
        return SimpleNamespace(id=111)


def test_qr_login_from_the_web(client, conn):
    r = client.post("/api/connectors/telegram/login", headers=CSRF)
    rid = r.json()["id"]
    assert r.json()["status"] == "pending"
    user = asyncio.run(
        telegram_auth.web_login(conn, FakeTelegram(SimpleNamespace(id=111)), poll=0.01)
    )
    assert user.id == 111
    status = client.get(f"/api/connectors/telegram/login/{rid}").json()
    assert status["status"] == "qr"  # the QR was shown; the service then continues ingesting


def test_qr_login_with_two_step_password(client, conn):
    from telethon.errors import SessionPasswordNeededError

    rid = client.post("/api/connectors/telegram/login", headers=CSRF).json()["id"]
    fake = FakeTelegram(SessionPasswordNeededError(request=None))

    async def scenario():
        task = asyncio.create_task(telegram_auth.web_login(conn, fake, poll=0.01))
        for _ in range(200):
            await asyncio.sleep(0.01)
            if (
                client.get(f"/api/connectors/telegram/login/{rid}").json()["status"]
                == "password_needed"
            ):
                break
        r = client.post(
            f"/api/connectors/telegram/login/{rid}/password",
            json={"password": "hunter2"},
            headers=CSRF,
        )
        assert r.status_code == 200
        return await task

    assert asyncio.run(scenario()).id == 111
    assert fake.passwords == ["hunter2"]
    row = conn.execute("SELECT status, secret FROM telegram_login WHERE id = %s", (rid,)).fetchone()
    assert row["status"] == "done" and row["secret"] is None  # password wiped


def test_qr_svg_rendered_while_waiting(client, conn):
    rid = client.post("/api/connectors/telegram/login", headers=CSRF).json()["id"]
    conn.execute(
        "UPDATE telegram_login SET status = 'qr', qr_url = 'tg://login?token=x' WHERE id = %s",
        (rid,),
    )
    svg = client.get(f"/api/connectors/telegram/login/{rid}").json()["qr_svg"]
    assert svg.startswith("<svg") or "<svg" in svg[:200]
    assert secrets  # imported for sealing in the API
