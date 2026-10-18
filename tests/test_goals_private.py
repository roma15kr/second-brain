import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from kb import goals, library, scopes
from kb.config import Config
from kb.mcp_server import make_search
from kb.routines import briefs
from tests.fakes import call
from tests.test_brief_ai import FakeLlm

NOW = datetime(2026, 10, 20, 9, 0, tzinfo=UTC)
PLAN = (
    "# Quokka plan 2026\n\n## Channels\n\nWe will launch on 2 new marketplaces by the end of 2026,"
    " starting with Epicentr.\n\n## Marketing\n\nKeep ROAS on Meta at 4 or higher in Q4."
)


def add(conn, title, kind, text, ai_allowed=None, scope="quokka"):
    return library.add_document(
        conn, title, kind, [scope], "d.md", text.encode(), scopes.known(conn), NOW, ai_allowed
    )


def test_ai_disallowed_document_never_in_prompt(conn, pg_url, config):
    from kb import db
    from kb.mcp_server import build_server

    note = add(conn, "Health", "note", "Xyloquartz therapy results", scope="personal")
    add(conn, "Private plan", "plan", "Xyloquartz expansion goal by 2026-12-31", ai_allowed=False)
    # MCP (Claude is an AI service) never sees them; the owner's own web search does
    mcp_search = make_search(lambda: db.connect(pg_url), config)
    assert mcp_search("Xyloquartz", None, None, None, None, None, 10) == []
    mine = mcp_search("Xyloquartz", None, None, None, None, None, 10, None, True)
    assert {r["title"] for r in mine} == {"Health", "Private plan"}
    # no goal proposals from a private plan
    llm = FakeLlm({"goals": []})
    assert goals.cycle(conn, Config(), llm, NOW) == 0 and llm.calls == []
    # briefs never include library text
    conn.execute(
        "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,"
        " last_activity_at) VALUES ('s', 'c', 'email_thread', '{quokka}', 'Dealer', 'hello', %s)",
        (NOW - timedelta(hours=2),),
    )
    brief_llm = FakeLlm({"sections": [], "focus": []})
    briefs.run_morning(conn, NOW, brief_llm, Config())
    assert "Xyloquartz" not in brief_llm.calls[0]["text"]
    # MCP get_item refuses the private document
    item_id = conn.execute(
        "SELECT id FROM items WHERE source_item_key = %s", (f"doc-{note}",)
    ).fetchone()["id"]
    server = build_server(lambda: db.connect(pg_url), config)
    with pytest.raises(ToolError, match="private"):
        asyncio.run(call(server, "get_item", {"item_id": item_id}))


def test_goals_proposed_need_confirmation(conn):
    doc = add(conn, "Quokka plan 2026", "plan", PLAN)
    llm = FakeLlm(
        {
            "goals": [
                {
                    "title": "Launch on 2 new marketplaces",
                    "measure": "listings live",
                    "deadline": "2026-12-31",
                    "quote": "We will launch on 2 new marketplaces by the end of 2026",
                },
                {
                    "title": "Hire a CTO",
                    "measure": "",
                    "deadline": "",
                    "quote": "we will hire a CTO next month",
                },
            ]
        }
    )
    assert goals.cycle(conn, Config(), llm, NOW) == 1  # the invented quote is dropped
    [g] = goals.listing(conn)
    assert g["status"] == "proposed" and g["scope"] == "quokka" and g["deadline"] == "2026-12-31"
    assert "Epicentr" in g["source_excerpt"] and g["document"] == "Quokka plan 2026"
    assert goals.confirmed(conn) == []
    assert goals.cycle(conn, Config(), llm, NOW) == 0  # same version: not proposed again
    goals.act(conn, g["id"], "confirm", NOW, measure="2 listings live")
    assert [c["measure"] for c in goals.confirmed(conn)] == ["2 listings live"]
    # a new version replaces unconfirmed proposals but keeps confirmed goals
    library.add_version(
        conn, doc, "d.md", (PLAN + "\n\nWe will open a showroom in Kyiv.").encode(), NOW
    )
    goals.cycle(conn, Config(), FakeLlm({"goals": []}), NOW)
    assert [c["title"] for c in goals.confirmed(conn)] == ["Launch on 2 new marketplaces"]


def test_goals_api(conn, pg_url, config):
    from fastapi.testclient import TestClient

    from kb import db
    from kb.api import auth
    from kb.api.app import build_app

    doc = add(conn, "Plan", "plan", PLAN)
    conn.execute(
        "INSERT INTO goals (document_id, title, scope, source_excerpt)"
        " VALUES (%s, 'ROAS 4', 'quokka', 'x')",
        (doc,),
    )
    gid = conn.execute("SELECT id FROM goals").fetchone()["id"]
    app = build_app(
        None,
        connect=lambda: db.connect(pg_url),
        rp=auth.RelyingParty("https://os.x"),
        config=config,
    )
    c = TestClient(app, base_url="https://os.x")
    c.cookies.set(auth.SESSION_COOKIE, auth.create_session(conn, "t", datetime.now(UTC)))
    h = {"X-KB-Request": "1"}
    assert (
        c.post(
            f"/api/goals/{gid}", json={"action": "confirm", "deadline": "2026-12-31"}, headers=h
        ).status_code
        == 200
    )
    assert c.get("/api/goals").json()["goals"][0]["status"] == "confirmed"
    assert (
        c.post(f"/api/goals/{gid}", json={"action": "edit", "scope": "acme"}, headers=h).status_code
        == 400
    )
    assert c.post("/api/goals/999", json={"action": "remove"}, headers=h).status_code == 404
