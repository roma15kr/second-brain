from datetime import date, datetime

import httpx
import pytest

from kb import db, indexer
from kb.connectors import imap
from kb.mcp_server import BearerAuth, build_app, build_server
from tests.fakes import FakeImap, make_email

TOKEN = "test-token"


async def _ok_app(scope, receive, send):
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b"inner"})


@pytest.mark.parametrize("header", [None, "Bearer wrong", f"Basic {TOKEN}"])
async def test_mcp_requires_token(header):
    transport = httpx.ASGITransport(app=BearerAuth(_ok_app, TOKEN))
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as client:
        headers = {"Authorization": header} if header else {}
        r = await client.post("/mcp", headers=headers)
    assert r.status_code == 401
    assert "inner" not in r.text


async def test_mcp_accepts_valid_token_and_health_is_open():
    transport = httpx.ASGITransport(app=BearerAuth(_ok_app, TOKEN))
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as client:
        assert (
            await client.post("/mcp", headers={"Authorization": f"Bearer {TOKEN}"})
        ).text == "inner"
        assert (await client.get("/health")).status_code == 200


def test_build_app_refuses_empty_token(pg_url):
    with pytest.raises(ValueError, match="KB_MCP_TOKEN"):
        build_app(lambda: db.connect(pg_url), "")


async def test_search_tool_returns_evidence(conn, pg_url, source, config):
    fake = FakeImap()
    fake.add(
        1, make_email("Marketplace contract", "Signed contract for Rozetka"), datetime(2026, 9, 1)
    )
    imap.sync_folder(conn, fake, source, "INBOX", today=date(2026, 10, 10))
    while indexer.run_once(conn, config):
        pass
    server = build_server(lambda: db.connect(pg_url))
    tools = {t.name: t for t in await server.list_tools()}
    assert "search" in tools and "scopes" in str(tools["search"].input_schema)
    result = await server.call_tool("search", {"query": "Rozetka"})
    assert "Marketplace contract" in str(result)
