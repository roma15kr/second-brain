from datetime import UTC, datetime, timedelta

from kb import db, health, jobs
from kb.config import Config, ImapSource
from kb.mcp_server import build_server
from tests.fakes import call


def cfg(monkeypatch):
    monkeypatch.setenv("U", "u")
    monkeypatch.setenv("P", "p")
    return Config(
        sources=[
            ImapSource(
                id="mail",
                type="imap",
                host="h",
                username_env="U",
                password_env="P",
                poll_seconds=60,
            )
        ]
    )


def test_never_synced_is_unhealthy(conn, monkeypatch):
    s = health.status(conn, cfg(monkeypatch))
    assert s["healthy"] is False and s["sources"][0]["healthy"] is False


def test_ok_then_expired_credentials_reported(conn, monkeypatch):
    c = cfg(monkeypatch)
    health.record_ok(conn, "mail", new=3, backfilling=True)
    s = health.status(conn, c)["sources"][0]
    assert s["healthy"] and s["backfilling"] and s["detail"]["new"] == 3
    health.record_error(conn, "mail", "LoginError: [AUTHENTICATIONFAILED] Invalid credentials")
    s = health.status(conn, c)["sources"][0]
    assert not s["healthy"] and "AUTHENTICATIONFAILED" in s["last_error"]
    health.record_ok(conn, "mail", new=0, backfilling=False)
    assert health.status(conn, c)["sources"][0]["last_error"] is None


def test_stale_after_three_intervals(conn, monkeypatch):
    c = cfg(monkeypatch)
    old = (datetime.now(UTC) - timedelta(minutes=4)).isoformat()
    conn.execute(
        "INSERT INTO sync_state (source_id, key, value) VALUES ('mail', 'health', %s)",
        (f'{{"last_ok": "{old}"}}',),
    )
    assert health.status(conn, c)["sources"][0]["healthy"] is False


def test_index_queue_and_failed_jobs(conn, monkeypatch):
    c = cfg(monkeypatch)
    health.record_ok(conn, "mail")
    jid = jobs.enqueue(conn, "index.raw", {"raw_id": 1})
    jobs.enqueue(conn, "index.raw", {"raw_id": 2})
    conn.execute(
        "UPDATE jobs SET attempts = %s, last_error = 'boom' WHERE id = %s", (jobs.MAX_ATTEMPTS, jid)
    )
    s = health.status(conn, c)
    assert s["index_queue"]["pending"] == 1 and s["index_queue"]["failed"] == 1
    assert s["index_queue"]["recent_errors"][0]["error"] == "boom"
    assert s["healthy"] is False


async def test_status_tool(conn, pg_url, monkeypatch):
    server = build_server(lambda: db.connect(pg_url), cfg(monkeypatch))
    r = await call(server, "status", {})
    assert "index_queue" in str(r.structured_content)
