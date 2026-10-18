import json
from datetime import datetime

import pytest
from pywebpush import WebPushException

from kb import push
from kb.routines import KYIV

SUB = {"endpoint": "https://push.example/abc", "keys": {"p256dh": "p", "auth": "a"}}
DAY = datetime(2026, 10, 20, 8, 0, tzinfo=KYIV)


@pytest.fixture(autouse=True)
def vapid(monkeypatch):
    public, private = push.generate_vapid_keys()
    monkeypatch.setenv("WEB_PUSH_VAPID_PUBLIC_KEY", public)
    monkeypatch.setenv("WEB_PUSH_VAPID_PRIVATE_KEY", private)


class Recorder:
    def __init__(self, status=None):
        self.calls, self.status = [], status

    def __call__(self, **kw):
        self.calls.append(kw)
        if self.status:
            raise WebPushException("gone", response=type("R", (), {"status_code": self.status})())


def brief(conn, headline="Morning brief: 3 need your reply"):
    return conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
        " VALUES ('morning', now(), now(), %s, %s, 'data') RETURNING id",
        (headline, json.dumps([{"title": "rdim", "text": "secret contract details", "items": []}])),
    ).fetchone()["id"]


def test_push_payload_has_no_content(conn, monkeypatch):
    push.subscribe(conn, SUB, "iPhone")
    rec = Recorder()
    monkeypatch.setattr(push, "webpush", rec)
    bid = brief(conn)
    assert push.notify_brief(conn, bid, DAY) == 1
    data = json.loads(rec.calls[0]["data"])
    assert data == {
        "title": "Second brain",
        "body": "Morning brief: 3 need your reply",
        "url": f"/briefs/{bid}?via=push",
    }
    assert "contract" not in rec.calls[0]["data"]


def test_gone_subscription_deleted(conn):
    push.subscribe(conn, SUB, "iPhone")
    assert push.send(conn, "morning", "h", "/", DAY, Recorder(status=410)) == 0
    assert conn.execute("SELECT count(*) AS n FROM push_subscriptions").fetchone()["n"] == 0


def test_other_errors_keep_subscription(conn):
    push.subscribe(conn, SUB, "iPhone")
    push.send(conn, "morning", "h", "/", DAY, Recorder(status=500))
    row = conn.execute("SELECT last_error FROM push_subscriptions").fetchone()
    assert row["last_error"]


def test_quiet_hours_no_push_but_brief_stored(conn):
    from kb.routines.scheduler import run_due

    push.subscribe(conn, SUB, "iPhone")
    rec = Recorder()
    late = datetime(2026, 10, 20, 22, 30, tzinfo=KYIV)
    run_due(
        conn,
        {"evening": lambda c, now: brief(c)},
        late,
        notify=lambda c, bid, now: push.send(c, "evening", "h", "/", now, rec),
    )
    assert rec.calls == []
    assert conn.execute("SELECT count(*) AS n FROM briefs").fetchone()["n"] == 1
    assert push.in_quiet_hours(datetime(2026, 10, 20, 7, 29, tzinfo=KYIV))
    assert not push.in_quiet_hours(datetime(2026, 10, 20, 7, 30, tzinfo=KYIV))


def test_routine_toggle_per_device(conn):
    push.subscribe(conn, SUB, "iPhone")
    conn.execute("UPDATE push_subscriptions SET routines = '{morning}'")
    rec = Recorder()
    push.send(conn, "revision", "h", "/", DAY, rec)
    assert rec.calls == []
    push.send(conn, "morning", "h", "/", DAY, rec)
    assert len(rec.calls) == 1


def test_push_failure_does_not_fail_the_run(conn):
    from kb.routines.scheduler import run_due

    def boom(c, bid, now):
        raise RuntimeError("push service down")

    run_due(conn, {"morning": lambda c, now: brief(c)}, DAY, notify=boom)
    assert conn.execute("SELECT status FROM routine_runs").fetchone()["status"] == "done"


def test_subscribe_validates_and_upserts(conn):
    with pytest.raises(ValueError):
        push.subscribe(conn, {"endpoint": "x"}, "d")
    a = push.subscribe(conn, SUB, "old")
    b = push.subscribe(conn, SUB, "new")
    assert a == b


def test_kb_routines_wires_push(monkeypatch):
    from kb import cli
    from kb.routines import scheduler

    seen: dict[str, object] = {}
    monkeypatch.setenv("DATABASE_URL", "postgresql://unused")
    monkeypatch.setenv("KB_CONFIG_YAML", "sources: []")
    monkeypatch.setattr(
        scheduler, "serve", lambda connect, runners, notify, **kw: seen.update(n=notify)
    )
    cli.main(["routines"])
    assert seen["n"] is push.notify_brief
