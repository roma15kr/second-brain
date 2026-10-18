import re
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from kb import db
from kb.api import auth
from kb.api.app import PUBLIC_API, build_app

NOW = datetime(2026, 10, 19, 8, 0, tzinfo=UTC)
RP = auth.RelyingParty("https://os.example.com")
CSRF = {"X-KB-Request": "1"}


@pytest.fixture
def app(conn, pg_url):
    clock = {"now": NOW}
    application = build_app(
        None, connect=lambda: db.connect(pg_url), rp=RP, clock=lambda: clock["now"]
    )
    application.state.clock = clock
    return application


@pytest.fixture
def client(app):
    return TestClient(app, base_url="https://os.example.com")


def signed_in(client, conn, now=NOW):
    client.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "test", now))
    return client


def test_all_routes_require_session(app, client):
    protected = [
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute) and route.path.startswith("/api/")
        for method in route.methods or ()
        if route.path not in PUBLIC_API
    ]
    assert ("POST", "/api/auth/logout") in protected
    for method, path in protected:
        url = re.sub(r"\{[^}]+\}", "1", path)
        r = client.request(method, url, headers=CSRF)
        assert r.status_code == 401, (method, path, r.status_code)
        assert r.json() == {"detail": "sign in required"}


def test_session_cookie_grants_access_until_logout(client, conn):
    signed_in(client, conn)
    assert client.get("/api/auth/me").json()["signed_in"] is True
    assert client.get("/api/nope").status_code == 404  # past the session check
    assert client.post("/api/auth/logout", headers=CSRF).status_code == 200
    assert client.get("/api/nope").status_code == 401


def test_expired_session_is_refused(app, client, conn):
    signed_in(client, conn)
    app.state.clock["now"] = NOW + timedelta(days=auth.SESSION_DAYS + 1)
    assert client.get("/api/nope").status_code == 401


def test_session_expiry_slides_with_use(app, client, conn):
    signed_in(client, conn)
    app.state.clock["now"] = NOW + timedelta(days=20)
    assert client.get("/api/nope").status_code == 404  # used on day 20 → extended
    app.state.clock["now"] = NOW + timedelta(days=45)
    assert client.get("/api/nope").status_code == 404


def test_csrf_header_required_on_post(client):
    r = client.post("/api/auth/login/begin")
    assert r.status_code == 403 and "X-KB-Request" in r.json()["detail"]
    assert client.post("/api/auth/login/begin", headers=CSRF).status_code == 200


def test_setup_code_required_for_first_passkey(app, client, conn):
    def begin(code=None):
        return client.post("/api/auth/register/begin", json={"setup_code": code}, headers=CSRF)

    assert begin().status_code == 403
    assert begin("WRONG-CODE").status_code == 403
    code = auth.new_setup_code(conn, NOW)
    r = begin(code.lower())  # case and dash do not matter
    assert r.status_code == 200
    assert r.json()["rp"]["id"] == "os.example.com" and r.json()["challenge"]
    assert auth.CHALLENGE_COOKIE in r.cookies
    app.state.clock["now"] = NOW + auth.SETUP_CODE_TTL + timedelta(seconds=1)
    assert begin(code).status_code == 403  # expired


def _fake_verified(monkeypatch):
    monkeypatch.setattr(
        auth,
        "verify_registration_response",
        lambda **kw: SimpleNamespace(
            credential_id=b"cred-1", credential_public_key=b"pk", sign_count=0
        ),
    )


def test_first_passkey_consumes_code_and_signs_in(client, conn, monkeypatch):
    _fake_verified(monkeypatch)
    code = auth.new_setup_code(conn, NOW)
    client.post("/api/auth/register/begin", json={"setup_code": code}, headers=CSRF)
    r = client.post("/api/auth/register/finish", json={"credential": {"id": "x"}}, headers=CSRF)
    assert r.status_code == 200 and auth.SESSION_COOKIE in r.cookies
    assert client.get("/api/auth/me").json() == {
        "signed_in": True,
        "has_passkeys": True,
        "needs_passkey": False,
    }
    stranger = TestClient(client.app, base_url="https://os.example.com")
    r = stranger.post("/api/auth/register/begin", json={"setup_code": code}, headers=CSRF)
    assert r.status_code == 403  # a passkey exists: only a signed-in session may add more


def test_finish_without_begin_is_refused(client):
    r = client.post("/api/auth/register/finish", json={"credential": {}}, headers=CSRF)
    assert r.status_code == 400


def test_login_rejects_unknown_passkey(client):
    client.post("/api/auth/login/begin", headers=CSRF)
    r = client.post(
        "/api/auth/login/finish", json={"credential": {"rawId": "dW5rbm93bg"}}, headers=CSRF
    )
    assert r.status_code == 401 and auth.SESSION_COOKIE not in r.cookies


def test_kb_web_setup_code_command(pg_url, conn, monkeypatch, capsys):
    from kb import cli

    monkeypatch.setenv("DATABASE_URL", pg_url)
    cli.main(["web", "setup-code"])
    found = re.search(r"setup code: (\S+)", capsys.readouterr().out)
    assert found is not None
    code = found.group(1)
    assert auth._valid_setup_code(conn, code, datetime.now(UTC)) is not None


def test_moving_to_a_new_domain_allows_enrolment_with_a_setup_code(conn, pg_url, monkeypatch):
    _fake_verified(monkeypatch)
    old = TestClient(
        build_app(None, connect=lambda: db.connect(pg_url), rp=RP, clock=lambda: NOW),
        base_url="https://os.example.com",
    )
    code = auth.new_setup_code(conn, NOW)
    old.post("/api/auth/register/begin", json={"setup_code": code}, headers=CSRF)
    old.post("/api/auth/register/finish", json={"credential": {"id": "x"}}, headers=CSRF)

    new_rp = auth.RelyingParty("https://os.zhukovsky.example")
    new = TestClient(
        build_app(None, connect=lambda: db.connect(pg_url), rp=new_rp, clock=lambda: NOW),
        base_url="https://os.zhukovsky.example",
    )
    assert new.get("/api/auth/me").json()["has_passkeys"] is False
    assert new.post("/api/auth/register/begin", json={}, headers=CSRF).status_code == 403
    fresh = auth.new_setup_code(conn, NOW)
    r = new.post("/api/auth/register/begin", json={"setup_code": fresh}, headers=CSRF)
    assert r.status_code == 200 and r.json()["rp"]["id"] == "os.zhukovsky.example"
