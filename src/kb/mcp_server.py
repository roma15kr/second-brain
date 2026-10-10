"""MCP server: thin, LLM-free retrieval tools behind a bearer token."""

from __future__ import annotations

import hmac
from collections.abc import Callable
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from kb.db import Conn
from kb.search import SearchFilters, search

INSTRUCTIONS = (
    "Personal knowledge base of the owner's mail and Telegram chats. "
    "Tools return ranked evidence with citations; compose answers yourself and cite item ids. "
    "Scopes: personal, digisoft, quokka, rdim, unsorted."
)


def build_server(get_conn: Callable[[], Conn]) -> MCPServer:
    server = MCPServer(name="second-brain", instructions=INSTRUCTIONS)

    def run(
        query: str,
        kinds: list[str] | None,
        scopes: list[str] | None,
        sources: list[str] | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        filters = SearchFilters(
            scopes=scopes,
            sources=sources,
            kinds=kinds,
            date_from=date.fromisoformat(date_from) if date_from else None,
            date_to=date.fromisoformat(date_to) if date_to else None,
        )
        with get_conn() as conn:
            return [e.to_dict() for e in search(conn, query, filters, limit)]

    @server.tool(name="search")
    def search_all(
        query: str,
        scopes: list[str] | None = None,
        sources: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search everything (mail and Telegram). Exact words, names, ids and phrases work best
        for now. Optional filters: scopes, source ids, date_from/date_to (YYYY-MM-DD)."""
        return run(query, None, scopes, sources, date_from, date_to, limit)

    @server.tool(name="search_mail")
    def search_mail(
        query: str,
        scopes: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search email only. Same filters as `search`."""
        return run(query, ["email"], scopes, None, date_from, date_to, limit)

    @server.tool(name="search_chats")
    def search_chats(
        query: str,
        scopes: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search Telegram messages only (allowlisted chats). Each result is one message; its
        locator links to the message in Telegram when possible."""
        return run(query, ["tg_message"], scopes, None, date_from, date_to, limit)

    return server


class BearerAuth:
    """Rejects any HTTP request without the expected bearer token."""

    def __init__(self, app: ASGIApp, token: str) -> None:
        if not token:
            raise ValueError("KB_MCP_TOKEN must be set")
        self.app = app
        self.expected = f"Bearer {token}".encode()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if scope.get("path") == "/health":
                await _respond(send, 200, b"ok")
                return
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):
                await _respond(send, 401, b"unauthorized")
                return
        await self.app(scope, receive, send)


async def _respond(send: Send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [
                (b"content-type", b"text/plain"),
                (b"content-length", str(len(body)).encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


def build_app(get_conn: Callable[[], Conn], token: str) -> ASGIApp:
    server = build_server(get_conn)
    # Host-header checks are disabled: access is limited by the private network + bearer token.
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host="0.0.0.0",
    )
    return BearerAuth(app, token)
