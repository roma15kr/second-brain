import argparse
from datetime import UTC, datetime, timedelta

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
        self.fail_comments_times = 1
        self.omit_last_page = False
        self.replies: dict[str, list[dict]] = {}
        self.groups: list[dict] = [{"id": "G9", "name": "DTC"}]
        self.oldest_first = False
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
        if path == "/group":
            return httpx.Response(200, json={"groups": self.groups})
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
                key=lambda t: -int(t["date_updated"]),  # newest first, like ClickUp's default
            )
            if self.oldest_first != (q.get("reverse") == "true"):  # the server's own default
                found.reverse()
            page = int(q.get("page", "0"))
            chunk = found[page * 100 : (page + 1) * 100]
            body: dict[str, object] = {"tasks": chunk}
            if not self.omit_last_page:
                body["last_page"] = (page + 1) * 100 >= len(found)
            return httpx.Response(200, json=body)
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
            if self.fail_comments_for == tid and self.fail_comments_times > 0:
                self.fail_comments_times -= 1
                return httpx.Response(
                    429, headers={"X-RateLimit-Reset": "1760000060"}, json={"err": "Rate limit"}
                )
            # newest first, 25 per page; older pages via start/start_id (ClickUp API v2)
            allc = sorted(self.comments.get(tid, []), key=lambda c: -int(c.get("date", 0)))
            if "start" in q:
                allc = [c for c in allc if int(c.get("date", 0)) < int(q["start"])]
            return httpx.Response(200, json={"comments": allc[:25]})
        if path.startswith("/comment/") and path.endswith("/reply"):
            return httpx.Response(200, json={"comments": self.replies.get(path.split("/")[2], [])})
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


def test_status_reports_clickup_feed(conn, fake, account):
    from kb import health

    [s] = health.clickup_status(conn)
    assert s["lists_syncing"] == 1 and s["tasks"] == 0 and s["healthy"] is False  # never synced
    fake.tasks["L1"] = [task("a", 1000)]
    n = clickup.sync_account(conn, fake.client(), account)
    health.record_ok(conn, clickup.source_id(account.id), new=n)
    [s] = health.clickup_status(conn)
    assert s["tasks"] == 1 and s["healthy"] is True and s["last_error"] is None
    conn.execute("UPDATE clickup_lists SET sync = false")
    [s] = health.clickup_status(conn)
    assert s["note"] == "no list is marked and set to sync yet"


def test_large_list_newest_first_without_last_page_flag_resumes_cheaply(conn, fake, account):
    fake.tasks["L1"] = [task(f"t{i}", 1000 + i) for i in range(250)]
    fake.omit_last_page = True
    fake.fail_comments_for = "t100"  # rate limit in the middle of the second page, twice
    fake.fail_comments_times = 2
    for _ in range(2):
        with pytest.raises(clickup.RateLimited):
            clickup.sync_account(conn, fake.client(), account)
    assert conn.execute("SELECT cursor_ms FROM clickup_lists").fetchone()["cursor_ms"] == 0
    before = sum(1 for m, p, _ in fake.requests if p.endswith("/comment"))
    clickup.sync_account(conn, fake.client(), account)
    comment_calls = sum(1 for m, p, _ in fake.requests if p.endswith("/comment")) - before
    assert len(tasks_in_db(conn)) == 250  # nothing skipped, whatever the order
    assert comment_calls == 250 - 149  # tasks stored before the interruption are not refetched
    assert conn.execute("SELECT cursor_ms FROM clickup_lists").fetchone()["cursor_ms"] == 1249


def test_client_throttles_under_the_rate_limit():
    import time

    c = clickup.ClickUpClient(
        "pk",
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"user": {}})),
        min_interval=0.05,
    )
    start = time.monotonic()
    for _ in range(4):
        c.user()
    assert time.monotonic() - start >= 0.15


def comment(cid, when, text, who="Олена", replies=0):
    return {
        "id": cid,
        "date": str(when),
        "comment_text": text,
        "user": {"username": who, "email": "olena@quokka.example"},
        "reply_count": replies,
    }


def test_all_comments_with_replies_are_stored_oldest_first_and_chunked(conn, fake, account):
    fake.tasks["L1"] = [task("a", 1000)]
    fake.comments["a"] = [
        comment(f"c{i}", 1000 + i, f"comment number {i} " + "detail " * 20) for i in range(60)
    ]
    fake.comments["a"][3]["reply_count"] = 1
    fake.replies["c3"] = [comment("r1", 1003, "the customs broker number is 4417", who="Макс")]
    clickup.sync_account(conn, fake.client(), account)
    item = tasks_in_db(conn)["a"]
    text = item["raw_text"]
    assert text.index("comment number 0 ") < text.index("comment number 59 ")  # chronological
    assert "↳" in text and "customs broker number is 4417" in text  # threaded reply
    assert item["metadata"]["comments"] == 61 and item["metadata"]["newest_comment_id"] == "c59"
    assert item["content_hash"]  # summaries know when the task changed
    chunks = conn.execute("SELECT metadata FROM items WHERE kind = 'clickup_comments'").fetchall()
    assert len(chunks) > 1 and all(c["metadata"]["parent_item_id"] == item["id"] for c in chunks)


def test_re_marking_a_list_relabels_its_tasks_and_comment_chunks(client, conn, fake, account):
    fake.tasks["L1"] = [task("a", 1000)]
    fake.comments["a"] = [comment(f"c{i}", 1000 + i, "detail " * 30) for i in range(20)]
    clickup.sync_account(conn, fake.client(), account)
    r = client.post("/api/connectors/clickup/lists/L1", json={"scopes": ["digisoft"]}, headers=CSRF)
    assert r.json() == {"relabelled_tasks": 1}
    kinds = conn.execute(
        "SELECT DISTINCT kind, scopes FROM items WHERE kind LIKE 'clickup%%'"
    ).fetchall()
    assert {k["kind"] for k in kinds} == {"clickup_task", "clickup_comments"}
    assert all(k["scopes"] == ["digisoft"] for k in kinds)


def test_newest_tasks_come_first_whatever_the_api_default(conn, fake, account):
    fake.oldest_first = True
    fake.tasks["L1"] = [task(f"t{i}", 1000 + i) for i in range(5)]
    c = fake.client()
    clickup.sync_account(conn, c, account)
    first = [r for m, p, r in fake.requests if p == "/list/L1/task"][-1]
    assert first.get("reverse") == "true" and c.reverse_for_newest is True
    stored = conn.execute(
        "SELECT source_item_key FROM items WHERE kind = 'clickup_task' ORDER BY id"
    ).fetchall()
    assert [r["source_item_key"] for r in stored] == ["t4", "t3", "t2", "t1", "t0"]


def test_new_comment_without_task_update_is_picked_up(conn, fake, account):
    recent = int(datetime.now(UTC).timestamp() * 1000)
    fake.tasks["L1"] = [task("a", recent)]
    fake.comments["a"] = [comment("c1", recent, "first")]
    clickup.sync_account(conn, fake.client(), account)
    fake.comments["a"].append(comment("c2", recent + 1, "customs papers arrived"))
    assert clickup.sync_account(conn, fake.client(), account) == 0  # task itself unchanged
    assert clickup.refresh_recent_comments(conn, fake.client(), account) == 1
    assert "customs papers arrived" in tasks_in_db(conn)["a"]["raw_text"]
    assert clickup.refresh_recent_comments(conn, fake.client(), account) == 0


def test_sync_in_time_slices_continues_where_it_stopped(conn, fake, account):
    fake.tasks["L1"] = [task(f"t{i}", 1000 + i) for i in range(30)]
    n, finished = clickup.sync_account_for(conn, fake.client(), account, seconds=0)
    assert finished is False and n == 0
    assert conn.execute("SELECT cursor_ms FROM clickup_lists").fetchone()["cursor_ms"] == 0
    n, finished = clickup.sync_account_for(conn, fake.client(), account, seconds=None)
    assert finished is True and n == 30


def test_migration_resets_for_a_full_comment_reread(conn):
    from kb import db as dbmod

    sql = next(s for name, s in dbmod.migration_files() if name.startswith("0027"))
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, metadata) VALUES"
        " ('clickup-1', 'x', 'clickup_task', '{\"date_updated\": \"5\", \"list\": \"L\"}')"
    )
    conn.execute(sql)
    meta = conn.execute("SELECT metadata FROM items").fetchone()["metadata"]
    assert "date_updated" not in meta and meta["list"] == "L"


# --- items for the owner (11.3) -------------------------------------------------------------

OWNER = {"id": 1, "username": "Owner", "email": "me@example.com"}
OLENA = {"id": 7, "username": "Олена", "email": "olena@quokka.example"}


@pytest.fixture
def watched(conn, fake, account):
    """Notifications start now; the owner is user 1, the DTC group is G9."""
    clickup.ensure_identity(conn, fake.client(), account, datetime.now(UTC) - timedelta(hours=1))
    return account


def now_ms(minutes=0):
    return int((datetime.now(UTC) + timedelta(minutes=minutes)).timestamp() * 1000)


def notes(conn):
    return [
        (r["kind"], r["actor"])
        for r in conn.execute("SELECT * FROM clickup_notifications ORDER BY key")
    ]


def test_mention_of_owner_notifies_once(conn, fake, watched):
    fake.tasks["L1"] = [task("a", now_ms())]
    fake.comments["a"] = [
        {
            **comment("c1", now_ms(), "@Owner can you approve the banners?"),
            "comment": [{"text": "can you approve "}, {"type": "tag", "user": OWNER}],
        }
    ]
    clickup.sync_account(conn, fake.client(), watched)
    clickup.refresh_recent_comments(conn, fake.client(), watched)  # seeing it again
    fake.tasks["L1"] = [task("a", now_ms(1))]
    clickup.sync_account(conn, fake.client(), watched)
    assert notes(conn) == [("mentioned", "Олена")]


def test_group_assignment_notifies(conn, fake, watched):
    fake.tasks["L1"] = [{**task("b", now_ms()), "group_assignees": [{"id": "G9", "name": "DTC"}]}]
    clickup.sync_account(conn, fake.client(), watched)
    fake.tasks["L1"] = [{**task("b", now_ms(2)), "group_assignees": [{"id": "G9", "name": "DTC"}]}]
    clickup.sync_account(conn, fake.client(), watched)
    assert notes(conn) == [("group_assigned", "")]


def test_own_comments_and_old_items_do_not_notify(conn, fake, watched):
    old = int((datetime.now(UTC) - timedelta(days=3)).timestamp() * 1000)
    fake.tasks["L1"] = [
        {**task("old", old, assignee="me@example.com"), "assignees": [OWNER]},
        {**task("mine", now_ms()), "watchers": [OWNER]},
    ]
    fake.comments["mine"] = [{**comment("c9", now_ms(), "done"), "user": OWNER}]
    clickup.sync_account(conn, fake.client(), watched)
    assert notes(conn) == []


def test_followed_tasks_new_task_and_comments(conn, fake, watched):
    fake.tasks["L1"] = [
        {
            **task("f", now_ms()),
            "watchers": [OWNER, OLENA],
            "date_created": str(now_ms()),
            "creator": OLENA,
        }
    ]
    fake.comments["f"] = [comment("c5", now_ms(), "photos uploaded")]
    clickup.sync_account(conn, fake.client(), watched)
    assert sorted(notes(conn)) == [("followed_comment", "Олена"), ("followed_new_task", "")]


def test_pending_notifications_pushed_by_routines(conn, fake, watched, monkeypatch):
    from kb import push
    from kb.routines import KYIV

    sent = []

    def fake_send(c, routine, headline, url, now, **k):
        sent.append((routine, headline, url))
        return 1

    monkeypatch.setattr(push, "send", fake_send)
    fake.tasks["L1"] = [{**task("a", now_ms()), "watchers": [OWNER]}]
    fake.comments["a"] = [
        {**comment("c1", now_ms(), "hi"), "comment": [{"type": "tag", "user": OWNER}]},
        comment("c2", now_ms(), "follow-up"),
        comment("c3", now_ms(), "another"),
    ]
    clickup.sync_account(conn, fake.client(), watched)
    item = conn.execute("SELECT id FROM items WHERE source_item_key = 'a'").fetchone()["id"]
    night = datetime(2026, 10, 20, 23, 30, tzinfo=KYIV)
    assert clickup.push_pending(conn, night) == 0 and sent == []  # held for the brief
    conn.execute("UPDATE clickup_notifications SET handled_at = NULL")
    day = datetime(2026, 10, 21, 10, 0, tzinfo=KYIV)
    clickup.push_pending(conn, day)
    assert sent[0] == ("clickup", "ClickUp: Олена mentioned you", f"/c/{item}")
    assert sent[1] == ("clickup", "ClickUp: 2 task updates you follow", f"/c/{item}")
    fake.comments["a"].append(comment("c4", now_ms(), "more"))
    clickup.refresh_recent_comments(conn, fake.client(), watched)
    clickup.push_pending(conn, day + timedelta(minutes=5))
    assert len(sent) == 2  # followed activity waits for the 15-minute window
    clickup.push_pending(conn, day + timedelta(minutes=16))
    assert len(sent) == 3


def test_followed_chat_channels_are_searchable_and_notify(conn, fake, watched):
    msgs = [
        {
            "id": "m1",
            "content": "Rozetka banners are live",
            "date": now_ms(),
            "user_id": "7",
            "type": "message",
        },
        {"id": "m2", "content": "thanks", "date": now_ms(1), "user_id": "1", "type": "message"},
    ]
    original = fake.handler

    def v3(request):
        p = request.url.path
        if p.endswith("/chat/channels"):
            assert request.url.params["is_follower"] == "true"
            return httpx.Response(
                200, json={"data": [{"id": "CH1", "name": "marketing"}], "next_cursor": ""}
            )
        if p.endswith("/chat/channels/CH1/messages"):
            return httpx.Response(200, json={"data": list(reversed(msgs)), "next_cursor": ""})
        if p == "/api/v2/team":
            return httpx.Response(
                200,
                json={
                    "teams": [
                        {
                            "id": "T1",
                            "name": "Quokka",
                            "members": [{"user": OLENA}, {"user": OWNER}],
                        }
                    ]
                },
            )
        return original(request)

    fake.handler = v3
    clickup.ensure_identity(
        conn, fake.client(), watched, datetime.now(UTC) - timedelta(hours=1), refresh_group=True
    )
    assert clickup.sync_chat(conn, fake.client(), watched, datetime.now(UTC)) == 2
    item = conn.execute("SELECT * FROM items WHERE kind = 'clickup_chat'").fetchone()
    assert "Олена: Rozetka banners are live" in item["raw_text"] and item["scopes"] == ["quokka"]
    assert item["title"].startswith("#marketing")
    assert notes(conn) == [("followed_chat", "Олена")]  # the owner's own message is not
    assert clickup.sync_chat(conn, fake.client(), watched, datetime.now(UTC)) == 0  # cursor kept
