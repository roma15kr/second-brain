import argparse
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from kb import cli, db, secrets
from kb.api import auth
from kb.api.app import build_app
from kb.connectors import clickup

CSRF = {"X-KB-Request": "1"}


def task(
    tid, updated, status="to do", status_type="open", assignee="olena@quokka.example", due=None
):
    return {
        "id": tid,
        "name": f"Update listings {tid}",
        "text_content": "New photos for Rozetka",
        "status": {"status": status, "type": status_type},
        "date_created": "1760000000000",
        "date_updated": str(updated),
        "due_date": due,
        "assignees": [{"id": 7, "username": "Олена", "email": assignee}],
        "creator": {"id": 1, "username": "Owner", "email": "me@example.com"},
        "url": f"https://app.clickup.com/t/{tid}",
        "list": {"id": "L1", "name": "Marketplaces"},
    }


class FakeClickUp:
    """ClickUp API v2 shapes (recorded from the docs), served in memory."""

    def __init__(self):
        self.tasks: dict[str, list[dict]] = {"L1": []}
        self.comments = {}
        self.requests = []
        self.fail_comments_for = None
        self.created = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, q = request.url.path.removeprefix("/api/v2"), dict(request.url.params)
        self.requests.append((request.method, path, q))
        if request.headers.get("Authorization") != "pk_test":
            return httpx.Response(401, json={"err": "Token invalid"})
        if path == "/user":
            return httpx.Response(200, json={"user": {"id": 1, "email": "me@example.com"}})
        if path == "/team":
            return httpx.Response(200, json={"teams": [{"id": "T1", "name": "Quokka"}]})
        if path == "/team/T1/space":
            return httpx.Response(200, json={"spaces": [{"id": "S1", "name": "Quokka"}]})
        if path == "/space/S1/folder":
            return httpx.Response(
                200,
                json={
                    "folders": [{"name": "Sales", "lists": [{"id": "L1", "name": "Marketplaces"}]}]
                },
            )
        if path == "/space/S1/list":
            return httpx.Response(200, json={"lists": [{"id": "L2", "name": "HR"}]})
        if path == "/list/L1/task" and request.method == "GET":
            if "date_created_gt" in q:
                gt = int(q["date_created_gt"])
                return httpx.Response(
                    200, json={"tasks": [t for t in self.created if int(t["date_created"]) > gt]}
                )
            gt = int(q["date_updated_gt"])
            found = sorted(
                (t for t in self.tasks["L1"] if int(t["date_updated"]) > gt),
                key=lambda t: -int(t["date_updated"]),
            )
            return httpx.Response(200, json={"tasks": found, "last_page": True})
        if path == "/list/L1/task" and request.method == "POST":
            body = __import__("json").loads(request.content)
            t = {
                **task(f"new{len(self.created) + 1}", 9_000_000_000_000),
                **body,
                "date_created": "9000000000000",
            }
            self.created.append(t)
            return httpx.Response(200, json=t)
        if path.startswith("/task/") and path.endswith("/comment"):
            tid = path.split("/")[2]
            if self.fail_comments_for == tid:
                return httpx.Response(
                    429, headers={"X-RateLimit-Reset": "1760000060"}, json={"err": "Rate limit"}
                )
            return httpx.Response(200, json={"comments": self.comments.get(tid, [])})
        return httpx.Response(404, json={"err": path})

    def client(self, token="pk_test"):
        return clickup.ClickUpClient(token, transport=httpx.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def key(monkeypatch):
    monkeypatch.setenv("KB_SECRET_KEY", "a-long-test-passphrase-for-the-secret-key")


@pytest.fixture
def fake():
    return FakeClickUp()


@pytest.fixture
def account(conn):
    from psycopg.types.json import Jsonb

    aid = conn.execute(
        "INSERT INTO connector_accounts (kind, label, settings, secret)"
        " VALUES ('clickup', 'Quokka', %s, %s) RETURNING id",
        (Jsonb({"team_id": "T1"}), secrets.seal({"token": "pk_test"})),
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO clickup_lists (list_id, account_id, space_id, list_name, sync, scopes)"
        " VALUES ('L1', %s, 'S1', 'Marketplaces', true, '{quokka}')",
        (aid,),
    )
    return clickup.Account(aid, "pk_test", "T1")


def tasks_in_db(conn):
    return {
        r["source_item_key"]: r
        for r in conn.execute("SELECT * FROM items WHERE kind = 'clickup_task'")
    }


def test_sync_list_incremental_cursor(conn, fake, account):
    fake.tasks["L1"] = [task("a", 1000), task("b", 2000)]
    fake.comments["a"] = [
        {
            "comment_text": "Photos ready tomorrow",
            "user": {"username": "Олена", "email": "olena@quokka.example"},
        }
    ]
    assert clickup.sync_account(conn, fake.client(), account) == 2
    assert conn.execute("SELECT cursor_ms FROM clickup_lists").fetchone()["cursor_ms"] == 2000
    items = tasks_in_db(conn)
    assert items["a"]["scopes"] == ["quokka"] and "Photos ready tomorrow" in items["a"]["raw_text"]
    assert items["a"]["locator"] == "https://app.clickup.com/t/a"
    assert "email:olena@quokka.example" in items["a"]["identity_keys"]
    assert clickup.sync_account(conn, fake.client(), account) == 0  # nothing new
    assert fake.requests[-1][2]["date_updated_gt"] == "2000"
    fake.tasks["L1"].append(task("c", 3000))
    assert clickup.sync_account(conn, fake.client(), account) == 1
    assert set(tasks_in_db(conn)) == {"a", "b", "c"}


def test_429_backoff_resumes(conn, fake, account):
    fake.tasks["L1"] = [task("a", 1000), task("b", 2000)]
    fake.fail_comments_for = "a"
    with pytest.raises(clickup.RateLimited) as e:
        clickup.sync_account(conn, fake.client(), account)
    assert e.value.reset_at == 1760000060
    fake.fail_comments_for = None
    clickup.sync_account(conn, fake.client(), account)
    assert set(tasks_in_db(conn)) == {"a", "b"}  # nothing lost, nothing duplicated
    assert (
        conn.execute("SELECT count(*) AS n FROM items WHERE kind = 'clickup_task'").fetchone()["n"]
        == 2
    )


def test_closed_task_closes_linked_loop(conn, fake, account):
    conn.execute(
        "INSERT INTO loops (kind, title, clickup_task_id) VALUES ('owed_to_me', 'Listings', 'a')"
    )
    fake.tasks["L1"] = [task("a", 1000)]
    clickup.sync_account(conn, fake.client(), account)
    assert conn.execute("SELECT status FROM loops").fetchone()["status"] == "open"
    fake.tasks["L1"] = [task("a", 2000, status="complete", status_type="closed")]
    clickup.sync_account(conn, fake.client(), account)
    assert conn.execute("SELECT status FROM loops").fetchone()["status"] == "done"


def test_ingest_loop_syncs_and_pauses_on_rate_limit(conn, pg_url, fake, account, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", pg_url)
    monkeypatch.setenv("KB_CONFIG_YAML", "sources: []")
    real = clickup.ClickUpClient
    monkeypatch.setattr(
        clickup,
        "ClickUpClient",
        lambda token: real(token, transport=httpx.MockTransport(fake.handler)),
    )
    fake.tasks["L1"] = [task("a", 1000)]
    cli.cmd_ingest(argparse.Namespace(once=True))
    assert set(tasks_in_db(conn)) == {"a"}
    last_run: dict[str, float] = {}
    fake.tasks["L1"].append(task("b", 2000))
    fake.fail_comments_for = "b"
    cli._sync_clickup(last_run)
    assert last_run[f"clickup-{account.id}:until"] > 0  # paused until the reset time


@pytest.fixture
def client(conn, pg_url, config, fake):
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    app.state.clickup_client = fake.client
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def test_connect_choose_and_mark_lists(client, conn):
    assert (
        client.post("/api/connectors/clickup", json={"token": "wrong"}, headers=CSRF).status_code
        == 400
    )
    r = client.post("/api/connectors/clickup", json={"token": "pk_test"}, headers=CSRF)
    assert r.json()["lists"] == 2
    over = client.get("/api/connectors/clickup").json()
    assert {(x["folder"], x["list"], x["sync"]) for x in over["lists"]} == {
        ("Sales", "Marketplaces", False),
        ("", "HR", False),
    }
    stored = conn.execute("SELECT settings::text AS s, secret FROM connector_accounts").fetchone()
    assert "pk_test" not in stored["s"] and b"pk_test" not in bytes(stored["secret"])
    # a list must be marked before it syncs
    assert (
        client.post(
            "/api/connectors/clickup/lists/L1", json={"sync": True}, headers=CSRF
        ).status_code
        == 400
    )
    ok = client.post(
        "/api/connectors/clickup/lists/L1",
        json={"sync": True, "scopes": ["quokka"], "default_for_drafts": True},
        headers=CSRF,
    )
    assert ok.status_code == 200
    row = conn.execute(
        "SELECT sync, scopes, default_for_drafts FROM clickup_lists WHERE list_id = 'L1'"
    ).fetchone()
    assert row == {"sync": True, "scopes": ["quokka"], "default_for_drafts": True}


# --- task drafts (11.2) -----------------------------------------------------------------------

from kb.assistant import suggestions  # noqa: E402

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)


def draft(conn, **extra):
    return suggestions.propose(
        conn,
        "task",
        {
            "list_id": "L1",
            "name": "Update listings with new photos",
            "description": "From the Quokka sync",
            "assignee_emails": ["olena@quokka.example"],
            "assignee_name": "Олена",
            "due_date": "2026-10-23",
            **extra,
        },
        reason="Олена will update the listings by Friday",
    )


def test_task_created_only_from_approved(conn, fake, account):
    sid = draft(conn)
    assert fake.created == []  # proposing creates nothing
    other = draft(conn, name="Something else")
    suggestions.discard(conn, other, "not needed", NOW)
    assert fake.created == []
    original = fake.handler

    def with_members(request):
        if request.url.path.endswith("/list/L1/member"):
            return httpx.Response(
                200, json={"members": [{"id": 7, "email": "olena@quokka.example"}]}
            )
        return original(request)

    fake.handler = with_members
    ref = suggestions.approve(conn, sid, NOW, {"due_date": "2026-10-24"}, lambda: fake.client())
    [t] = fake.created
    assert ref == t["id"] and t["assignees"] == [7] and f"[kb:{sid}]" in t["description"]
    assert t["due_date"] == int(
        datetime(2026, 10, 24, 15, 0, tzinfo=UTC).timestamp() * 1000
    )  # 18:00 Kyiv
    row = conn.execute(
        "SELECT status, applied_ref, edited FROM suggestions WHERE id = %s", (sid,)
    ).fetchone()
    assert row == {"status": "applied", "applied_ref": t["id"], "edited": True}
    assert (
        suggestions.approve(conn, sid, NOW, None, lambda: fake.client()) == t["id"]
    )  # no second task
    assert len(fake.created) == 1


def test_create_task_idempotent_retry(conn, fake, account):
    sid = draft(conn)
    # an earlier attempt created the task in ClickUp but crashed before recording it
    conn.execute(
        "UPDATE suggestions SET status = 'applying', attempt_started_at = %s WHERE id = %s",
        (NOW, sid),
    )
    fake.created.append(
        {
            **task("x1", 9_000_000_000_000),
            "description": f"... [kb:{sid}]",
            "date_created": "9000000000000",
        }
    )
    ref = suggestions.approve(conn, sid, NOW, None, lambda: fake.client())
    assert ref == "x1" and len(fake.created) == 1
    assert not any(m == "POST" for m, *_ in fake.requests)


def test_closed_task_closes_loop(conn, fake, account):
    sid = draft(conn, assignee_emails=[])
    ref = suggestions.approve(conn, sid, NOW, None, lambda: fake.client())
    loop = conn.execute("SELECT kind, status, counterpart, clickup_task_id FROM loops").fetchone()
    assert loop == {
        "kind": "owed_to_me",
        "status": "open",
        "counterpart": "Олена",
        "clickup_task_id": ref,
    }
    fake.tasks["L1"] = [task(ref, 9_100_000_000_000, status="complete", status_type="closed")]
    clickup.sync_account(conn, fake.client(), account)
    assert conn.execute("SELECT status FROM loops").fetchone()["status"] == "done"


def test_due_tasks_in_morning_brief(conn, fake, account, config):
    from kb.routines import briefs

    due = str(int(datetime(2026, 10, 19, 12, 0, tzinfo=UTC).timestamp() * 1000))
    fake.tasks["L1"] = [
        task("mine", 1000, assignee="me@example.com", due=due),
        task("theirs", 1000, due=due),
        task("done", 1000, assignee="me@example.com", due=due, status_type="closed"),
    ]
    clickup.sync_account(conn, fake.client(), account)
    briefs.run_morning(conn, NOW, None, config)
    brief = briefs.latest(conn, ["morning"])
    assert brief is not None
    section = next(s for s in brief["sections"] if s["title"] == "ClickUp: due today & overdue")
    assert [i["title"] for i in section["items"]] == ["Update listings mine"]
    assert "overdue since 2026-10-19" in section["items"][0]["summary"]


def test_approval_api(conn, pg_url, config, fake, account):
    sid = draft(conn, assignee_emails=[])
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    app.state.clickup_factory = lambda c: lambda: fake.client()
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    assert [s["id"] for s in c.get("/api/suggestions").json()["suggestions"]] == [sid]
    r = c.post(
        f"/api/suggestions/{sid}/approve",
        json={"payload": {"name": "Update listings (edited)"}},
        headers=CSRF,
    )
    assert r.status_code == 200 and fake.created[0]["name"] == "Update listings (edited)"
    assert (
        c.post(f"/api/suggestions/{sid}/discard", json={}, headers=CSRF).status_code == 400
    )  # already applied
    assert c.post("/api/suggestions/999/approve", json={}, headers=CSRF).status_code == 404
