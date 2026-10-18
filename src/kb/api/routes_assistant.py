"""Approval queue (assistant-actions spec): approve, edit then approve, or discard."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from kb.api.deps import get_conn
from kb.assistant import suggestions
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


@router.get("/api/suggestions")
def listing(conn: Db, status: str = "proposed") -> dict[str, Any]:
    return {"suggestions": suggestions.listing(conn, status)}


@router.post("/api/suggestions/{sid}/approve")
def approve(
    request: Request,
    conn: Db,
    sid: int,
    payload: Annotated[dict[str, Any] | None, Body(embed=True)] = None,
) -> dict[str, str]:
    factory = request.app.state.clickup_factory(conn)
    try:
        ref = suggestions.approve(conn, sid, datetime.now(UTC), payload, factory)
    except suggestions.SuggestionError as e:
        raise HTTPException(404 if str(e).startswith("no suggestion") else 400, str(e)) from e
    except Exception as e:  # the executor failed (e.g. ClickUp refused); recorded on the row
        raise HTTPException(502, f"could not apply: {e}") from e
    return {"applied_ref": ref}


@router.post("/api/suggestions/{sid}/discard")
def discard(
    conn: Db, sid: int, reason: Annotated[str | None, Body(embed=True)] = None
) -> dict[str, bool]:
    try:
        suggestions.discard(conn, sid, reason, datetime.now(UTC))
    except suggestions.SuggestionError as e:
        raise HTTPException(404 if str(e).startswith("no suggestion") else 400, str(e)) from e
    return {"ok": True}
