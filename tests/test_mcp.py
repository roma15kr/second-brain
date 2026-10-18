from datetime import date, datetime

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from kb import db, indexer
from kb.connectors import imap
from kb.mcp_server import BearerAuth, build_app, build_server
from tests.fakes import FakeImap, call, make_email

TOKEN = "t" * 40


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
    result = await call(server, "search", {"query": "Rozetka"})
    assert "Marketplace contract" in str(result)


async def test_mail_and_chat_tools_are_listed(pg_url):
    server = build_server(lambda: db.connect(pg_url))
    names = {t.name for t in await server.list_tools()}
    assert {"search", "search_mail", "search_chats"} <= names


async def test_bad_scope_and_date_reach_client_with_message(pg_url):
    server = build_server(lambda: db.connect(pg_url))
    with pytest.raises(ToolError, match="valid scopes: personal, digisoft, quokka, rdim"):
        await call(server, "search", {"query": "x", "scopes": ["acme"]})
    with pytest.raises(ToolError, match="YYYY-MM-DD"):
        await call(server, "search", {"query": "x", "date_from": "10/09/2026"})


def test_mcp_app_wires_the_reranker(pg_url, monkeypatch):
    """Regression: cmd_mcp once built the server without a reranker (results were all 'fused')."""
    from kb import mcp_server, rerank
    from kb.cli import build_mcp_app
    from kb.config import Config, EmbeddingConfig

    captured: dict[str, object] = {}

    def fake_build_app(get_conn, token, config=None, embedder=None, reranker=None):
        captured.update(token=token, reranker=reranker, embedder=embedder)
        return "app"

    monkeypatch.setattr(mcp_server, "build_app", fake_build_app)
    cfg = Config(embedding=EmbeddingConfig(enabled=False, cache_dir="/nonexistent"))
    assert build_mcp_app(cfg, pg_url, "tok", preload=False) == "app"
    assert isinstance(captured["reranker"], rerank.FastReranker)
    assert captured["reranker"].model_name == "jinaai/jina-reranker-v2-base-multilingual"
    assert captured["token"] == "tok" and captured["embedder"] is None


async def test_lockout_after_repeated_wrong_tokens_and_request_cap():
    from kb.mcp_server import RateLimiter

    now = [0.0]
    limiter = RateLimiter(max_failures=3, failure_window=600, max_requests=5, request_window=60)
    app = BearerAuth(_ok_app, TOKEN, limiter, clock=lambda: now[0])
    transport = httpx.ASGITransport(app=app)
    attacker = {"X-Forwarded-For": "203.0.113.9"}
    me = {"X-Forwarded-For": "198.51.100.1", "Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(transport=transport, base_url="http://kb") as client:
        for _ in range(3):
            assert (
                await client.post("/mcp", headers={**attacker, "Authorization": "Bearer x"})
            ).status_code == 401
        # locked out now, even with the right token
        locked = await client.post("/mcp", headers={**attacker, "Authorization": f"Bearer {TOKEN}"})
        assert locked.status_code == 429
        # other clients are unaffected, up to the request cap
        codes = [(await client.post("/mcp", headers=me)).status_code for _ in range(6)]
        assert codes == [200] * 5 + [429]
        now[0] += 601  # windows expire
        assert (
            await client.post("/mcp", headers={**attacker, "Authorization": f"Bearer {TOKEN}"})
        ).status_code == 200


def test_short_tokens_are_refused():
    with pytest.raises(ValueError, match="at least 32"):
        BearerAuth(_ok_app, "short-token")


def test_client_ip_prefers_cloudflare_header_over_spoofable_forwarded_for():
    from kb.mcp_server import client_ip

    spoofed = {
        "headers": [
            (b"x-forwarded-for", b"6.6.6.6, 203.0.113.9"),
            (b"cf-connecting-ip", b"203.0.113.9"),
        ],
        "client": ("172.18.0.5", 1234),
    }
    assert client_ip(spoofed) == "203.0.113.9"
    assert client_ip({"headers": [(b"x-forwarded-for", b"198.51.100.7")]}) == "198.51.100.7"
    assert client_ip({"headers": [], "client": ("10.0.0.2", 1)}) == "10.0.0.2"
