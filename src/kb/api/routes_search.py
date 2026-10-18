"""Search and Conversation pages (web-dashboard spec). Search runs in the MCP service, which
holds the embedding and reranking models (POST /internal/search with the MCP token); without
it (tests, local runs) the same search runs here with words only. Briefs are searched too."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request

from kb import scopes, units
from kb.api.deps import get_conn
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]
Searcher = Callable[[dict[str, Any]], list[dict[str, Any]]]
KINDS = {"mail": ["email_thread"], "chats": ["tg_conversation"]}
PAGE = 50


class SearchFailed(Exception):
    pass


def remote_searcher(url: str, token: str) -> Searcher:
    def run(params: dict[str, Any]) -> list[dict[str, Any]]:
        r = httpx.post(url, json=params, headers={"Authorization": f"Bearer {token}"}, timeout=20)
        if r.status_code == 400:
            raise SearchFailed(r.json().get("detail", "invalid search"))
        r.raise_for_status()
        return list(r.json()["results"])

    return run


def local_searcher(connect: Callable[[], Conn], config: Any) -> Searcher:
    from kb.mcp_server import make_search

    run_search = make_search(connect, config)

    def run(params: dict[str, Any]) -> list[dict[str, Any]]:
        from kb.people import PeopleError
        from kb.search import SearchError

        try:
            return run_search(
                params["query"],
                params.get("kinds"),
                params.get("scopes"),
                None,
                params.get("date_from"),
                params.get("date_to"),
                params.get("limit", 10),
                params.get("person"),
            )
        except (SearchError, PeopleError, ValueError) as e:
            raise SearchFailed(str(e)) from e

    return run


@router.get("/api/search")
def search(
    request: Request,
    conn: Db,
    q: str,
    scope: Annotated[list[str] | None, Query()] = None,
    kind: Literal["mail", "chats"] | None = None,
    person: str | None = None,
    date_from: Annotated[date | None, Query(alias="from")] = None,
    date_to: Annotated[date | None, Query(alias="to")] = None,
    limit: int = 10,
) -> dict[str, Any]:
    if not q.strip():
        return {"results": [], "briefs": []}
    params = {
        "query": q,
        "kinds": KINDS.get(kind or ""),
        "scopes": scope,
        "person": person,
        "date_from": date_from.isoformat() if date_from else None,
        "date_to": date_to.isoformat() if date_to else None,
        "limit": max(1, min(limit, 50)),
    }
    searcher: Searcher = request.app.state.searcher
    try:
        results = searcher(params)
    except SearchFailed as e:
        raise HTTPException(400, str(e)) from e
    found = conn.execute(
        "SELECT id, routine, headline, created_at FROM briefs"
        " WHERE to_tsvector('simple', headline || ' ' || sections::text)"
        " @@ plainto_tsquery('simple', %s) ORDER BY created_at DESC LIMIT 5",
        (q,),
    ).fetchall()
    return {
        "results": results,
        "briefs": [
            {
                "id": b["id"],
                "routine": b["routine"],
                "headline": b["headline"],
                "created_at": b["created_at"].isoformat(),
            }
            for b in found
        ],
    }


@router.get("/api/items/{item_id}")
def item(
    conn: Db, item_id: int, offset: int = 0, limit: int = PAGE, around: str | None = None
) -> dict[str, Any]:
    """A conversation with one page of messages; `around` (a message locator) opens the page
    that contains that message."""
    limit = max(1, min(limit, 200))
    if around:
        pos = conn.execute(
            "SELECT count(*) AS n FROM messages m JOIN items i ON i.source_id = m.source_id"
            " AND i.source_item_key = m.unit_key WHERE i.id = %s AND NOT m.hidden AND m.sent_at <"
            " (SELECT m2.sent_at FROM messages m2 JOIN items i2 ON i2.source_id = m2.source_id"
            "  AND i2.source_item_key = m2.unit_key WHERE i2.id = %s AND m2.locator = %s LIMIT 1)",
            (item_id, item_id, around),
        ).fetchone()
        if pos and pos["n"]:
            offset = (int(pos["n"]) // limit) * limit
    try:
        page = units.unit_messages(conn, item_id, offset, limit)
    except KeyError:
        raise HTTPException(404, f"no conversation {item_id}") from None
    it = page["item"]
    loops = conn.execute(
        "SELECT id, kind, title, status, due_date FROM loops WHERE item_id = %s ORDER BY id DESC",
        (item_id,),
    ).fetchall()
    return {
        "item_id": it["id"],
        "kind": it["kind"],
        "title": it["title"],
        "scopes": list(it["scopes"]),
        "participants": list(it["participants"]),
        "summary": it["summary"],
        "question": it["question"],
        "outcome": it["outcome"],
        "locator": it["locator"] if str(it["locator"] or "").startswith("https://") else None,
        "last_activity_at": it["last_activity_at"].isoformat() if it["last_activity_at"] else None,
        "total": page["total"],
        "offset": offset,
        "next_offset": page["next_offset"],
        "messages": [
            {
                "key": m["message_key"],
                "author": m["author"],
                "sent_at": m["sent_at"].isoformat(),
                "text": m["body"],
                "locator": m["locator"],
            }
            for m in page["messages"]
        ],
        "loops": [
            {
                "id": lp["id"],
                "kind": lp["kind"],
                "title": lp["title"],
                "status": lp["status"],
                "due_date": lp["due_date"].isoformat() if lp["due_date"] else None,
            }
            for lp in loops
        ],
    }


@router.post("/api/items/{item_id}/scope")
def set_scope(
    request: Request,
    conn: Db,
    item_id: int,
    scope: Annotated[str, Body(embed=True)],
    apply_to: Annotated[Literal["item", "sender", "chat"], Body(embed=True)] = "item",
) -> dict[str, str]:
    try:
        message = scopes.assign(
            conn,
            request.app.state.config,
            item_id,
            [scope],
            None if apply_to == "item" else apply_to,
        )
    except (scopes.ReviewError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    return {"result": message}
