"""MCP server: thin, LLM-free retrieval tools behind a bearer token."""

from __future__ import annotations

import functools
import hmac
import time
from collections.abc import Callable
from datetime import date
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.types import ASGIApp, Receive, Scope, Send

from kb import health, people, units
from kb.config import Config
from kb.db import Conn
from kb.ratelimit import RateLimiter, client_ip
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
        except (SearchError, people.PeopleError) as exc:
            raise ToolError(str(exc)) from None
        except ValueError as exc:  # e.g. date.fromisoformat
            raise ToolError(f"invalid argument: {exc}; dates use YYYY-MM-DD") from None

    return wrapper  # type: ignore[return-value]


def make_search(
    get_conn: Callable[[], Conn],
    config: Config | None = None,
    embedder: Any = None,
    reranker: Any = None,
) -> Callable[..., list[dict[str, Any]]]:
    """The search behind the MCP tools and the web OS's internal search route."""

    def run(
        query: str,
        kinds: list[str] | None,
        scopes: list[str] | None,
        sources: list[str] | None,
        date_from: str | None,
        date_to: str | None,
        limit: int,
        person: str | None = None,
        include_private: bool = False,
    ) -> list[dict[str, Any]]:
        filters = SearchFilters(
            scopes=scopes,
            sources=sources,
            kinds=kinds,
            include_private=include_private,
            date_from=date.fromisoformat(date_from) if date_from else None,
            date_to=date.fromisoformat(date_to) if date_to else None,
        )
        with get_conn() as conn:
            if person:
                filters.person_keys = people.keys_of(conn, people.resolve(conn, person))
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

    return run


def build_server(
    get_conn: Callable[[], Conn],
    config: Config | None = None,
    embedder: Any = None,
    reranker: Any = None,
) -> MCPServer:
    server = MCPServer(name="second-brain", instructions=INSTRUCTIONS)
    run = make_search(get_conn, config, embedder, reranker)

    @server.tool(name="search")
    @clear_errors
    def search_all(
        query: str,
        scopes: list[str] | None = None,
        sources: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
        person: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search everything (mail and Telegram) by words or meaning, in uk/ru/en. Optional
        filters: scopes, source ids, date_from/date_to (YYYY-MM-DD), person (id or name — only
        conversations involving that person; see the `person` tool)."""
        return run(query, None, scopes, sources, date_from, date_to, limit, person)

    @server.tool(name="search_mail")
    @clear_errors
    def search_mail(
        query: str,
        scopes: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
        person: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search email threads only. Same filters as `search`."""
        return run(query, ["email_thread"], scopes, None, date_from, date_to, limit, person)

    @server.tool(name="search_chats")
    @clear_errors
    def search_chats(
        query: str,
        scopes: list[str] | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 10,
        person: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search Telegram conversations only (allowlisted chats). Same filters as `search`."""
        return run(query, ["tg_conversation"], scopes, None, date_from, date_to, limit, person)

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
        if (item["metadata"] or {}).get("private"):
            raise SearchError(f"item {item_id} is private (AI may not read it)")
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

    @server.tool(name="person")
    @clear_errors
    def person(name_or_id: str) -> dict[str, Any]:
        """Look up a person across email and Telegram: names, identities (emails, Telegram
        accounts, phones), scopes, first/last interaction and recent conversations. A name that
        matches several people returns {"candidates": [...]} to choose from (call again by id)."""
        with get_conn() as conn:
            if not name_or_id.strip().isdigit():
                found = people.find(conn, name_or_id)
                if not found:
                    raise people.PeopleError(f"no person matches {name_or_id!r}")
                if len(found) > 1:
                    return {
                        "candidates": [
                            {"person_id": p["id"], "name": p["display_name"]} for p in found
                        ]
                    }
                return people.profile(conn, int(found[0]["id"]))
            return people.profile(conn, people.resolve(conn, name_or_id))

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
    """Bearer token on every request (ADR 0009 amendment: public HTTPS + token), with lockout
    after repeated wrong tokens and a per-client request cap."""

    def __init__(
        self,
        app: ASGIApp,
        token: str,
        limiter: RateLimiter | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not token:
            raise ValueError("KB_MCP_TOKEN must be set")
        if len(token) < 32:
            raise ValueError("KB_MCP_TOKEN must be at least 32 characters")
        self.app = app
        self.expected = f"Bearer {token}".encode()
        self.limiter = limiter or RateLimiter(
            max_failures=10, failure_window=600, max_requests=120, request_window=60
        )
        self.clock = clock

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            if scope.get("path") == "/health":
                await _respond(send, 200, b"ok")
                return
            ip, now = client_ip(scope), self.clock()
            if self.limiter.locked(ip, now):
                await _respond(send, 429, b"too many failed attempts; try later")
                return
            supplied = dict(scope.get("headers") or []).get(b"authorization", b"")
            if not hmac.compare_digest(supplied, self.expected):
                self.limiter.failed(ip, now)
                await _respond(send, 401, b"unauthorized")
                return
            if not self.limiter.allow_request(ip, now):
                await _respond(send, 429, b"rate limit exceeded")
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
    app.add_route(
        "/internal/search",
        internal_search(make_search(get_conn, config, embedder, reranker)),
        methods=["POST"],
    )
    return BearerAuth(app, token)


def internal_search(run: Callable[..., list[dict[str, Any]]]) -> Callable[..., Any]:
    """JSON search for the web OS (same token as MCP), so the models live in one process."""
    from starlette.concurrency import run_in_threadpool
    from starlette.requests import Request
    from starlette.responses import JSONResponse

    async def endpoint(request: Request) -> JSONResponse:
        body = await request.json()
        try:
            results = await run_in_threadpool(
                run,
                str(body.get("query", "")),
                body.get("kinds"),
                body.get("scopes"),
                body.get("sources"),
                body.get("date_from"),
                body.get("date_to"),
                int(body.get("limit", 10)),
                body.get("person"),
                bool(body.get("include_private", False)),  # only the web OS asks for these
            )
        except (SearchError, people.PeopleError, ValueError) as e:
            return JSONResponse({"detail": str(e)}, status_code=400)
        return JSONResponse({"results": results})

    return endpoint
