from datetime import UTC, datetime, time

import pytest
from fastapi.testclient import TestClient

from kb import db, push, settings_store
from kb.api import auth
from kb.api.app import build_app
from kb.config import Config, LlmConfig
from kb.routines import KYIV
from kb.routines.scheduler import run_due

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


def put(client, app):
    return client.put("/api/settings", json={"app": app}, headers=CSRF)


@pytest.mark.parametrize(
    ("app", "message"),
    [
        ({"schedule": {"morning": "25:00"}}, "schedule.morning"),
        ({"schedule": {"revision": [f"{h:02}:00" for h in range(9)]}}, "at most 8"),
        ({"schedule": {"weekly_review_day": 7}}, "weekly_review_day"),
        ({"ai_budget_usd": -1}, "ai_budget_usd"),
        ({"quiet_hours": {"start": "late"}}, "quiet_hours.start"),
    ],
)
def test_settings_validation(client, app, message):
    r = put(client, app)
    assert r.status_code == 400 and message in r.json()["detail"]


def test_defaults_and_round_trip(client):
    data = client.get("/api/settings").json()
    assert data["app"]["schedule"]["morning"] == "08:00:00"
    assert data["app"]["schedule"]["revision"] == ["11:00:00", "14:00:00", "17:00:00"]
    r = put(client, {"schedule": {"revision": ["16:00", "10:00", "10:00"]}, "ai_budget_usd": 15})
    assert r.json()["app"]["schedule"]["revision"] == ["10:00:00", "16:00:00"]  # sorted, unique
    assert client.get("/api/settings").json()["app"]["ai_budget_usd"] == 15


def test_changed_morning_time_moves_the_next_slot(conn):
    settings_store.save(conn, {"schedule": {"morning": "07:30"}})
    ran = []

    def morning(c, now):
        ran.append(now)
        return _brief(c)

    run_due(conn, {"morning": morning}, datetime(2026, 10, 20, 7, 31, tzinfo=KYIV))
    assert len(ran) == 1
    assert conn.execute("SELECT slot FROM routine_runs").fetchone()["slot"] == datetime(
        2026, 10, 20, 7, 30, tzinfo=KYIV
    )


def _brief(c):
    return c.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
        " VALUES ('morning', now(), now(), 'h', '[]', 'data') RETURNING id"
    ).fetchone()["id"]


def test_budget_from_settings_overrides_config(conn):
    assert settings_store.budget_usd(conn, Config(llm=LlmConfig(monthly_budget_usd=30))) == 30
    settings_store.save(conn, {"ai_budget_usd": 12.5})
    assert settings_store.budget_usd(conn, Config()) == 12.5


def test_quiet_hours_from_settings(conn, monkeypatch):
    settings_store.save(conn, {"quiet_hours": {"start": "21:00", "end": "08:00"}})
    monkeypatch.setenv("WEB_PUSH_VAPID_PRIVATE_KEY", "x")
    conn.execute("INSERT INTO push_subscriptions (endpoint, p256dh, auth) VALUES ('e', 'p', 'a')")
    sent = []
    push.send(
        conn,
        "morning",
        "h",
        "/",
        datetime(2026, 10, 20, 7, 45, tzinfo=KYIV),
        lambda **kw: sent.append(kw),
    )
    assert sent == []  # 07:45 is now inside quiet hours


def test_push_devices_routines(client, conn):
    sid = conn.execute(
        "INSERT INTO push_subscriptions (endpoint, p256dh, auth, device)"
        " VALUES ('e', 'p', 'a', 'iPhone') RETURNING id"
    ).fetchone()["id"]
    assert client.get("/api/settings/push").json()["devices"][0]["device"] == "iPhone"
    assert (
        client.put(
            f"/api/settings/push/{sid}", json={"routines": ["morning"]}, headers=CSRF
        ).status_code
        == 200
    )
    assert conn.execute("SELECT routines FROM push_subscriptions").fetchone()["routines"] == [
        "morning"
    ]
    assert (
        client.put(
            f"/api/settings/push/{sid}", json={"routines": ["lunch"]}, headers=CSRF
        ).status_code
        == 400
    )
    client.delete(f"/api/settings/push/{sid}", headers=CSRF)
    assert client.get("/api/settings/push").json()["devices"] == []


def test_scope_rule_rescopes_and_unsorted_list(client, conn):
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text) VALUES"
        " ('mail-test', 'u1', 'email_thread', '{unsorted}', 'Invoice', 'x')"
    )
    assert [i["title"] for i in client.get("/api/unsorted").json()["items"]] == ["Invoice"]
    r = client.post(
        "/api/settings/rules",
        json={"kind": "domain", "value": "Quokka.UA", "scopes": ["quokka"]},
        headers=CSRF,
    )
    assert r.status_code == 200
    again = {"kind": "domain", "value": "quokka.ua", "scopes": ["rdim"]}
    assert client.post("/api/settings/rules", json=again, headers=CSRF).status_code == 200
    rules = client.get("/api/settings/rules").json()["rules"]
    assert len(rules) == 1  # replaced, not duplicated
    assert rules[0]["value"] == "quokka.ua" and rules[0]["scopes"] == ["rdim"]
    bad = client.post(
        "/api/settings/rules",
        json={"kind": "domain", "value": "x", "scopes": ["acme"]},
        headers=CSRF,
    )
    assert bad.status_code == 400
    assert client.delete(f"/api/settings/rules/{rules[0]['id']}", headers=CSRF).status_code == 200


def test_schedule_converts_to_scheduler_settings(conn):
    settings_store.save(conn, {"schedule": {"weekly_review_day": 3, "weekly_review_time": "18:00"}})
    rs = settings_store.routine_settings(conn)
    assert rs.weekly_review == (3, time(18, 0)) and rs.morning == (time(8, 0),)
