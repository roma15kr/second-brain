"""Asking the assistant (assistant-requests spec; assistant-command-v1 tasks 1.1-1.2)."""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from kb import db
from kb.api import auth, routes_requests
from kb.api.app import build_app
from kb.assistant import agent
from kb.distill import Usage

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
CSRF = {"X-KB-Request": "1"}


class ScriptedLlm:
    """Each turn returns the next scripted step: a list of tool calls, or a final answer."""

    def __init__(self, *turns):
        self.turns, self.calls = list(turns), []

    def respond(self, model, instructions, items, tools, schema):
        self.calls.append({"items": list(items), "tools": [t["name"] for t in tools]})
        turn = self.turns.pop(0) if self.turns else {"answer": "done", "refs": []}
        if isinstance(turn, dict):
            return [{"type": "message"}], json.dumps(turn), Usage(1000, 100)
        out = [
            {"type": "function_call", "name": n, "arguments": json.dumps(a), "call_id": f"c{i}"}
            for i, (n, a) in enumerate(turn)
        ]
        return out, "", Usage(1000, 100)


def search_args(query):
    return {
        "query": query,
        "kind": None,
        "scopes": None,
        "person": None,
        "date_from": None,
        "date_to": None,
    }


def item(conn, title, text="", private=False):
    return conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text, summary,"
        " metadata, last_activity_at) VALUES ('mail-test', %s, 'email_thread', '{quokka}', %s, %s,"
        " %s, %s, %s) RETURNING id",
        (title, title, text, f"About {title}", Jsonb({"private": private}), NOW),
    ).fetchone()["id"]


def request(conn, text="what did we agree with Rozetka about delivery?"):
    tid = conn.execute(
        "INSERT INTO assistant_threads (title) VALUES ('t') RETURNING id"
    ).fetchone()["id"]
    return conn.execute(
        "INSERT INTO assistant_requests (thread_id, text) VALUES (%s, %s) RETURNING id", (tid, text)
    ).fetchone()["id"]


def fetch(conn, rid):
    return conn.execute("SELECT * FROM assistant_requests WHERE id = %s", (rid,)).fetchone()


def test_agent_answer_cites_only_tool_results(conn, config):
    terms = item(conn, "Rozetka delivery", "Delivery in 5 days, prepaid.")
    other = item(conn, "Unrelated")
    searcher = lambda p: [{"item_id": terms, "title": "Rozetka delivery", "kind": "email_thread"}]  # noqa: E731
    llm = ScriptedLlm(
        [("search", search_args("Rozetka delivery"))],
        {"answer": "Delivery in 5 days, prepaid.", "refs": [f"item:{terms}", f"item:{other}"]},
    )
    rid = request(conn)
    agent.run_request(conn, config, llm, searcher, rid, NOW)
    r = fetch(conn, rid)
    assert r["status"] == "done" and r["answer_md"] == "Delivery in 5 days, prepaid."
    assert r["refs"] == [f"item:{terms}"]  # `other` was never returned by a tool
    assert r["steps"] == [{"tool": "search", "summary": "searched for “Rozetka delivery”"}]
    assert float(r["cost_usd"]) > 0
    # the tool result went back to the model as data
    out = [i for i in llm.calls[1]["items"] if i.get("type") == "function_call_output"]
    assert f"item:{terms}" in out[0]["output"]


def test_agent_stops_at_tool_cap(conn, config):
    llm = ScriptedLlm(*[[("search", search_args(f"q{n}"))] for n in range(20)])
    rid = request(conn)
    agent.run_request(conn, config, llm, lambda p: [], rid, NOW)
    assert len(fetch(conn, rid)["steps"]) == agent.MAX_TOOL_CALLS
    assert llm.calls[-1]["tools"] == []  # the last turn may only answer
    assert fetch(conn, rid)["answer_md"] == agent.STEP_LIMIT


def test_private_document_never_read(conn, config):
    secret = item(conn, "Constitution", "the private text", private=True)
    llm = ScriptedLlm(
        [("get_item", {"id": secret})], {"answer": "It is private.", "refs": [f"item:{secret}"]}
    )
    rid = request(conn)
    agent.run_request(conn, config, llm, None, rid, NOW)
    out = next(i for i in llm.calls[1]["items"] if i.get("type") == "function_call_output")
    assert "private text" not in out["output"] and "private" in out["output"]
    assert fetch(conn, rid)["refs"] == []


def test_follow_up_sees_earlier_turns_and_failures_are_recorded(conn, config):
    rid = request(conn, "first question")
    agent.run_request(
        conn, config, ScriptedLlm({"answer": "first answer", "refs": []}), None, rid, NOW
    )
    tid = fetch(conn, rid)["thread_id"]
    rid2 = conn.execute(
        "INSERT INTO assistant_requests (thread_id, text) VALUES (%s, 'and then?') RETURNING id",
        (tid,),
    ).fetchone()["id"]
    llm = ScriptedLlm({"answer": "second", "refs": []})
    agent.run_request(conn, config, llm, None, rid2, NOW)
    contents = [i.get("content") for i in llm.calls[0]["items"]]
    assert contents == ["first question", "first answer", "and then?"]
    rid3 = request(conn)
    agent.run_request(conn, config, None, None, rid3, NOW)
    assert (
        fetch(conn, rid3)["status"] == "failed" and "OPENAI_API_KEY" in fetch(conn, rid3)["error"]
    )


@pytest.fixture
def app(conn, pg_url, config):
    a = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    a.state.assistant_submit = lambda job: job()  # run inline
    a.state.searcher = lambda p: []
    return a


def signed_in(app, conn):
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    return c


def test_request_runs_in_background_and_reports_steps(app, conn):
    app.state.assistant_llm = ScriptedLlm(
        [("search", search_args("netcup"))], {"answer": "Nothing found for netcup.", "refs": []}
    )
    client = signed_in(app, conn)
    r = client.post("/api/assistant/requests", json={"text": "find netcup invoices"}, headers=CSRF)
    ids = r.json()
    got = client.get(f"/api/assistant/requests/{ids['id']}").json()
    assert got["status"] == "done" and got["answer"] == "Nothing found for netcup."
    assert got["steps"][0]["summary"] == "searched for “netcup”"
    follow = client.post(
        "/api/assistant/requests",
        json={"text": "and in Telegram?", "thread_id": ids["thread_id"]},
        headers=CSRF,
    ).json()
    assert follow["thread_id"] == ids["thread_id"]
    t = client.get(f"/api/assistant/threads/{ids['thread_id']}").json()
    assert [q["text"] for q in t["requests"]] == ["find netcup invoices", "and in Telegram?"]
    [listed] = client.get("/api/assistant/threads").json()["threads"]
    assert listed["title"] == "find netcup invoices" and listed["requests"] == 2
    assert (
        client.post("/api/assistant/requests", json={"text": " "}, headers=CSRF).status_code == 400
    )


def test_running_requests_failed_after_restart(conn):
    rid = request(conn)
    assert routes_requests.fail_interrupted(conn) == 1
    assert fetch(conn, rid)["status"] == "failed"


def test_assistant_routes_require_session(app):
    anon = TestClient(app, base_url="https://os.x")
    assert anon.get("/api/assistant/threads").status_code == 401
    assert anon.post("/api/assistant/requests", json={"text": "x"}, headers=CSRF).status_code == 401


# --- actions from requests (slice 2) ------------------------------------------------------------


from kb import loops  # noqa: E402
from kb.assistant import actions, proactive, suggestions  # noqa: E402
from tests.test_email_drafts import FakeSmtp, thread  # noqa: E402


def clickup_list(conn, list_id, name, default=False):
    account = conn.execute(
        "INSERT INTO connector_accounts (kind, label, settings, secret)"
        " VALUES ('clickup', 'Quokka', '{}', '') RETURNING id"
    ).fetchone()["id"]
    conn.execute(
        "INSERT INTO clickup_lists (list_id, account_id, space_id, list_name, sync, scopes,"
        " default_for_drafts) VALUES (%s, %s, 'S', %s, true, '{quokka}', %s)",
        (list_id, account, name, default),
    )


def run(conn, config, *turns, text="x", searcher=None, rid=None):
    rid = rid or request(conn, text)
    llm = ScriptedLlm(*turns)
    agent.run_request(conn, config, llm, searcher, rid, NOW)
    return rid, llm


def test_request_creates_reply_draft_not_sent(conn, config):
    item = thread(conn)
    rid, _ = run(
        conn,
        config,
        [("draft_reply", {"item_id": item, "body": "We accept the new price from November."})],
        {"answer": "Prepared a reply for your approval.", "refs": [f"item:{item}"]},
    )
    [s] = suggestions.listing(conn)
    assert s["kind"] == "reply_email" and s["status"] == "proposed" and s["item_id"] == item
    row = conn.execute("SELECT origin, request_id FROM suggestions").fetchone()
    assert row == {"origin": "command", "request_id": rid}
    assert fetch(conn, rid)["created"] == [
        {"type": "suggestion", "id": s["id"], "kind": "draft_reply"}
    ]
    assert fetch(conn, rid)["refs"] == [f"item:{item}"]  # drafting a reply makes its thread citable


def test_new_email_mailbox_choice(conn, config):
    thread(conn, author="Dealer <dealer@example.com>")
    run(
        conn,
        config,
        [
            (
                "draft_email",
                {
                    "to": ["dealer@example.com"],
                    "subject": "Price list",
                    "body": "Please send the October price list.",
                },
            )
        ],
        {"answer": "Prepared.", "refs": []},
    )
    [s] = suggestions.listing(conn)
    assert s["kind"] == "email"
    suggestions.send_on_tap(conn, s["id"], NOW)
    smtp = FakeSmtp()
    suggestions.apply_mail(
        conn, config, NOW.replace(minute=1), open_imap=lambda b: None, open_smtp=lambda b: smtp
    )
    [msg] = smtp.sent
    # from the mailbox last used with that address
    assert msg["To"] == "dealer@example.com" and msg["From"] == "me@example.com"
    assert msg["Subject"] == "Price list" and msg["In-Reply-To"] is None


def test_task_draft_list_assignee_due(conn, config):
    clickup_list(conn, "L7", "Marketing")
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, title, metadata) VALUES"
        " ('clickup-1', 't1', 'clickup_task', 'x', %s)",
        (Jsonb({"assignees": ["Max Petrenko"], "assignee_emails": ["max@quokka.example"]}),),
    )
    run(
        conn,
        config,
        [
            (
                "draft_task",
                {
                    "name": "Update the banners",
                    "description": "",
                    "assignee": "Max",
                    "list": "marketing",
                    "due_date": "2026-10-23",
                },
            )
        ],
        {"answer": "Prepared.", "refs": []},
    )
    [s] = suggestions.listing(conn)
    p = s["payload"]
    assert s["kind"] == "task" and p["list_id"] == "L7" and p["due_date"] == "2026-10-23"
    assert p["assignee_emails"] == ["max@quokka.example"] and p["assignee_name"] == "Max Petrenko"


def test_follow_up_updates_pending_draft(conn, config):
    clickup_list(conn, "L1", "Ops", default=True)
    rid, _ = run(
        conn,
        config,
        [
            (
                "draft_task",
                {
                    "name": "Banners",
                    "description": "",
                    "assignee": None,
                    "list": None,
                    "due_date": None,
                },
            )
        ],
        {"answer": "Prepared.", "refs": []},
    )
    [s] = suggestions.listing(conn)
    tid = fetch(conn, rid)["thread_id"]
    rid2 = conn.execute(
        "INSERT INTO assistant_requests (thread_id, text)"
        " VALUES (%s, 'make it due Monday') RETURNING id",
        (tid,),
    ).fetchone()["id"]
    run(
        conn,
        config,
        [
            (
                "update_draft",
                {
                    "id": s["id"],
                    "body": None,
                    "subject": None,
                    "name": None,
                    "assignee": None,
                    "due_date": "2026-10-26",
                },
            )
        ],
        {"answer": "Updated.", "refs": []},
        rid=rid2,
    )
    assert suggestions.get(conn, s["id"])["payload"]["due_date"] == "2026-10-26"


def test_update_suggestion_refuses_other_threads(conn, config):
    other = suggestions.propose(conn, "email", {"to": ["a@b.c"], "subject": "s", "body": "b"})
    _rid, llm = run(
        conn,
        config,
        [
            (
                "update_draft",
                {
                    "id": other,
                    "body": "hijacked",
                    "subject": None,
                    "name": None,
                    "assignee": None,
                    "due_date": None,
                },
            )
        ],
        {"answer": "Could not.", "refs": []},
    )
    assert suggestions.get(conn, other)["payload"]["body"] == "b"
    out = next(i for i in llm.calls[1]["items"] if i.get("type") == "function_call_output")
    assert "not a pending draft from this conversation" in out["output"]


def test_remind_me_creates_loop_with_due(conn, config):
    rid, _ = run(
        conn,
        config,
        [("add_reminder", {"title": "Call Olena", "due_date": "2026-10-22", "person": "Olena"})],
        {"answer": "Added.", "refs": []},
    )
    [lp] = loops.list_loops(conn, NOW, "open")
    assert (
        lp["title"] == "Call Olena"
        and lp["due_date"] == "2026-10-22"
        and lp["counterpart"] == "Olena"
    )
    [entry] = fetch(conn, rid)["created"]
    assert entry == {
        "type": "loop",
        "id": lp["id"],
        "action": "add",
        "title": "Call Olena",
        "due": "2026-10-22",
    }


def test_loop_change_undo(conn, config):
    lid = loops.add_manual(conn, "Send the contract", NOW)
    rid, _ = run(
        conn,
        config,
        [("loop_action", {"loop_id": lid, "action": "done", "until": None})],
        {"answer": "Closed.", "refs": []},
    )
    assert loops.list_loops(conn, NOW, "open") == []
    actions.undo(conn, rid, 0, NOW)
    assert [lp["id"] for lp in loops.list_loops(conn, NOW, "open")] == [lid]
    assert fetch(conn, rid)["created"][0]["undone"] is True


def test_search_request_returns_filters(conn, config):
    hit = item(conn, "netcup invoice")
    rid, _ = run(
        conn,
        config,
        [
            (
                "search",
                {
                    "query": "netcup invoice",
                    "kind": "mail",
                    "scopes": None,
                    "person": "netcup",
                    "date_from": "2026-01-01",
                    "date_to": None,
                },
            )
        ],
        {"answer": "Found one.", "refs": [f"item:{hit}"]},
        searcher=lambda p: [{"item_id": hit, "title": "netcup invoice", "kind": "email_thread"}],
    )
    s = fetch(conn, rid)["search"]
    assert s["person"] == "netcup" and s["date_from"] == "2026-01-01" and s["kind"] == "mail"
    assert s["results"][0]["item_id"] == hit


def test_status_assistant_metric(conn):
    request(conn)
    a = suggestions.propose(
        conn, "email", {"to": ["a@b.c"], "subject": "", "body": "x"}, request_id=None
    )
    rid = request(conn)
    b = suggestions.propose(
        conn, "email", {"to": ["a@b.c"], "subject": "", "body": "x"}, request_id=rid
    )
    c = suggestions.propose(
        conn, "email", {"to": ["a@b.c"], "subject": "", "body": "x"}, request_id=rid
    )
    suggestions.discard(conn, a, None, NOW)
    suggestions.approve(conn, b, NOW)
    suggestions.discard(conn, c, None, NOW)
    conn.execute("UPDATE suggestions SET decided_at = now()")
    m = proactive.assistant_metric(conn, datetime.now(UTC))
    assert m["requests_7d"] == 2 and m["approved_from_requests"] == 0.5
    assert m["approved_from_routines"] == 0.0


def test_thread_shows_drafts_inline_and_undo_route(app, conn, config):
    item_id = thread(conn)
    lid = loops.add_manual(conn, "Send the contract", NOW)
    app.state.assistant_llm = ScriptedLlm(
        [
            ("draft_reply", {"item_id": item_id, "body": "Ok"}),
            ("loop_action", {"loop_id": lid, "action": "done", "until": None}),
        ],
        {"answer": "Done.", "refs": []},
    )
    client = signed_in(app, conn)
    ids = client.post(
        "/api/assistant/requests", json={"text": "reply ok and close it"}, headers=CSRF
    ).json()
    got = client.get(f"/api/assistant/requests/{ids['id']}").json()
    draft, change = got["created"]
    assert (
        draft["suggestion"]["payload"]["body"] == "Ok"
        and draft["suggestion"]["status"] == "proposed"
    )
    assert change["action"] == "done" and change["index"] == 1
    assert (
        client.post(f"/api/assistant/requests/{ids['id']}/undo/1", headers=CSRF).json()["undone"]
        is True
    )
    assert (
        client.post(f"/api/assistant/requests/{ids['id']}/undo/0", headers=CSRF).status_code == 400
    )
