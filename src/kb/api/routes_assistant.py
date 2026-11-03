"""Approval queue (assistant-actions spec): approve, edit then approve, or discard."""

from __future__ import annotations

import contextlib
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


@router.post("/api/suggestions/{sid}/send")
def send(
    conn: Db,
    sid: int,
    payload: Annotated[dict[str, Any] | None, Body(embed=True)] = None,
) -> dict[str, str]:
    """Sends ONE reply after a 10-second undo window (no bulk or scheduled sending)."""
    try:
        after = suggestions.send_on_tap(conn, sid, datetime.now(UTC), payload)
    except suggestions.SuggestionError as e:
        raise HTTPException(404 if str(e).startswith("no suggestion") else 400, str(e)) from e
    return {"send_after": after.isoformat()}


@router.post("/api/suggestions/{sid}/undo")
def undo(conn: Db, sid: int) -> dict[str, bool]:
    try:
        suggestions.undo_send(conn, sid)
    except suggestions.SuggestionError as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True}


@router.post("/api/items/{item_id}/reply-draft")
def reply_draft(conn: Db, item_id: int) -> dict[str, int]:
    from kb.assistant import mail

    try:
        return {"id": suggestions.reply_draft(conn, item_id)}
    except mail.MailError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/suggestions/{sid}/discard")
def discard(
    conn: Db, sid: int, reason: Annotated[str | None, Body(embed=True)] = None
) -> dict[str, bool]:
    try:
        suggestions.discard(conn, sid, reason, datetime.now(UTC))
    except suggestions.SuggestionError as e:
        raise HTTPException(404 if str(e).startswith("no suggestion") else 400, str(e)) from e
    return {"ok": True}


@router.post("/api/suggestions/moderate")
def moderate(
    request: Request,
    conn: Db,
    create: Annotated[list[int], Body(embed=True)],
    discard: Annotated[list[int], Body(embed=True)],
) -> dict[str, Any]:
    """The Moderate list (assistant-moderation-v1): creates the selected proposals and discards
    the rest in one action; one failing proposal does not stop the others."""
    factory = request.app.state.clickup_factory(conn)
    now = datetime.now(UTC)
    created: list[int] = []
    failed: dict[int, str] = {}
    for sid in create:
        try:
            suggestions.approve(conn, sid, now, None, factory)
            created.append(sid)
        except Exception as e:  # recorded on the row; reported back
            failed[sid] = str(e)[:200]
    for sid in discard:
        if sid in create:
            continue
        with contextlib.suppress(suggestions.SuggestionError):  # already decided
            suggestions.discard(conn, sid, "not chosen when moderating", now)
    return {"created": created, "failed": failed}


@router.post("/api/suggestions/{sid}/revise")
def revise(
    request: Request, conn: Db, sid: int, instruction: Annotated[str, Body(embed=True)]
) -> dict[str, Any]:
    """The owner's instruction (typed or dictated) for the AI to change a proposal."""
    from kb.assistant import revise as revising

    state = request.app.state
    try:
        s = revising.revise(
            conn, state.config, state.dictation_llm, sid, instruction, datetime.now(UTC)
        )
    except suggestions.SuggestionError as e:
        raise HTTPException(404 if str(e).startswith("no suggestion") else 400, str(e)) from e
    return {"suggestion": suggestions.one(conn, s["id"])}


@router.patch("/api/suggestions/{sid}")
def edit(conn: Db, sid: int, fields: Annotated[dict[str, Any], Body(embed=True)]) -> dict[str, Any]:
    """The owner's own wording for a proposal (title, text, assignee, due date)."""
    from kb.assistant import revise as revising

    try:
        s = revising.edit(conn, sid, fields, datetime.now(UTC))
    except suggestions.SuggestionError as e:
        raise HTTPException(404 if str(e).startswith("no suggestion") else 400, str(e)) from e
    return {"suggestion": suggestions.one(conn, s["id"])}


@router.post("/api/suggestions/merge")
def merge(
    request: Request,
    conn: Db,
    ids: Annotated[list[int], Body(embed=True)],
    instruction: Annotated[str, Body(embed=True)] = "",
) -> dict[str, Any]:
    """Several task proposals combined into one (optionally as the owner says)."""
    from kb.assistant import revise as revising

    state = request.app.state
    try:
        s = revising.merge(
            conn, state.config, state.dictation_llm, ids, instruction, datetime.now(UTC)
        )
    except suggestions.SuggestionError as e:
        raise HTTPException(404 if str(e).startswith("no suggestion") else 400, str(e)) from e
    return {"suggestion": suggestions.one(conn, s["id"])}
