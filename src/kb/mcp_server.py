"""MCP server: thin, LLM-free retrieval tools behind a bearer token."""

from __future__ import annotations

import functools
import hmac
from collections.abc import Callable
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from kb import health, units
from kb.config import Config
from kb.db import Conn
from kb.search import SearchError, SearchFilters, recent, search

INSTRUCTIONS = (
    "Personal knowledge base of the owner's mail and Telegram chats. "
    "Search matches exact words and meaning (any language: uk/ru/en). Tools return ranked "
    "evidence with citations and AI summaries; compose answers yourself and cite item ids. "
    "Scopes: personal, digisoft, quokka, rdim, unsorted."
)


def clear_errors[F: Callable[..., Any]](fn: F) -> F:
    """Report invalid input to the client with its specific message (not a generic crash)."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except SearchError as exc:
            raise ToolError(str(exc)) from None
        except ValueError as exc:  # e.g. date.fromisoformat
            raise ToolError(f"invalid argument: {exc}; dates use YYYY-MM-DD") from None

    return wrapper  # type: ignore[return-value]


def build_server(
    get_conn: Callable[[], Conn],
    config: Config | None = None,
    embedder: Any = None,
    reranker: Any = None,
) -> MCPServer:
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
            hits = search(
                conn,
                query,
                filters,
                limit,
                embedder,
                reranker=reranker,
                settings=config.search if config else None,
            )
            return [e.to_dict() for e in hits]

    @server.tool(name="search")
    @clear_errors
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
    @clear_errors
    def search_mail(
        query: str,
        scopes: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search email threads only. Same filters as `search`."""
        return run(query, ["email_thread"], scopes, None, date_from, date_to, limit)

    @server.tool(name="search_chats")
    @clear_errors
    def search_chats(
        query: str,
        scopes: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search Telegram conversations only (allowlisted chats). Each result is one conversation;
        its locator links to the first message in Telegram when possible."""
        return run(query, ["tg_conversation"], scopes, None, date_from, date_to, limit)

    @server.tool(name="get_item")
    @clear_errors
    def get_item(item_id: int, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        """Open one result (email thread or Telegram conversation) by its item_id: all messages
        oldest first, with authors and times. Long conversations are paged: pass next_offset."""
        if not 1 <= limit <= MAX_PAGE:
            raise SearchError(f"limit must be between 1 and {MAX_PAGE}")
        if offset < 0:
            raise SearchError("offset must be 0 or more")
        with get_conn() as conn:
            try:
                page = units.unit_messages(conn, item_id, offset, limit)
            except KeyError:
                raise SearchError(
                    f"no item with item_id {item_id}; use an item_id returned by a search tool"
                ) from None
        item = page["item"]
        return {
            "item_id": item["id"],
            "kind": item["kind"],
            "source": item["source_id"],
            "scopes": list(item["scopes"]),
            "title": item["title"],
            "participants": list(item["participants"]),
            "occurred_at": _iso(item["occurred_at"]),
            "last_activity_at": _iso(item["last_activity_at"]),
            "locator": item["locator"],
            "question": item["question"],
            "summary": item["summary"],
            "outcome": item["outcome"],
            "entities": item["entities"],
            "total_messages": page["total"],
            "offset": offset,
            "next_offset": page["next_offset"],
            "messages": [
                {
                    "author": m["author"],
                    "sent_at": _iso(m["sent_at"]),
                    "text": m["body"],
                    "locator": m["locator"],
                }
                for m in page["messages"]
            ],
        }

    @server.tool(name="recent_activity")
    @clear_errors
    def recent_activity(
        scopes: list[str] | None = None,
        kind: str | None = None,
        since: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Latest conversations by last activity. Optional: scopes, kind ('mail' or 'chats'),
        since (YYYY-MM-DD)."""
        kinds = {"mail": ["email_thread"], "chats": ["tg_conversation"], None: None}
        if kind not in kinds:
            raise SearchError("kind must be 'mail', 'chats' or omitted")
        filters = SearchFilters(
            scopes=scopes,
            kinds=kinds[kind],
            date_from=date.fromisoformat(since) if since else None,
        )
        with get_conn() as conn:
            return [e.to_dict() for e in recent(conn, filters, limit)]

    @server.tool(name="status")
    @clear_errors
    def status() -> dict[str, Any]:
        """Health of the knowledge base: per-source last sync and errors, backfill progress,
        index queue, item counts. Use when results look stale or incomplete."""
        if config is None:
            raise SearchError("status needs the server configuration")
        with get_conn() as conn:
            st = health.status(conn, config)
        state = getattr(reranker, "state", None)
        st["reranker"] = state() if callable(state) else {"enabled": reranker is not None}
        return st

    return server


MAX_PAGE = 200


def _iso(value: Any) -> str | None:
    return value.isoformat() if value is not None else None


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


def build_app(
    get_conn: Callable[[], Conn],
    token: str,
    config: Config | None = None,
    embedder: Any = None,
    reranker: Any = None,
) -> ASGIApp:
    server = build_server(get_conn, config, embedder, reranker)
    # Host-header checks are disabled: access is limited by the private network + bearer token.
    app = server.streamable_http_app(
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        host="0.0.0.0",
    )
    return BearerAuth(app, token)
