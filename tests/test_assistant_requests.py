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
