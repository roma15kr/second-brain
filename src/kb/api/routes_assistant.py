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


MAX_FILES, MAX_FILE_BYTES = 5, 10 * 1024 * 1024
IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp", "image/heic"}


@router.post("/api/suggestions/{sid}/files")
def add_file(
    conn: Db,
    sid: int,
    filename: Annotated[str, Body(embed=True)],
    mime: Annotated[str, Body(embed=True)],
    data: Annotated[str, Body(embed=True)],
) -> dict[str, int]:
    """An image for a ClickUp comment draft (base64), uploaded to the task when approved."""
    import base64
    import binascii

    s = conn.execute("SELECT kind, status FROM suggestions WHERE id = %s", (sid,)).fetchone()
    if s is None:
        raise HTTPException(404, f"no suggestion {sid}")
    if s["kind"] != "clickup_comment" or s["status"] not in ("proposed", "failed"):
        raise HTTPException(400, "images can be added to pending ClickUp comment drafts only")
    if mime not in IMAGE_TYPES:
        raise HTTPException(400, "add PNG, JPEG, GIF, WebP or HEIC images")
    try:
        raw = base64.b64decode(data, validate=True)
    except binascii.Error as e:
        raise HTTPException(400, "the file is not valid base64") from e
    if not raw or len(raw) > MAX_FILE_BYTES:
        raise HTTPException(400, "images are limited to 10 MB")
    count = conn.execute(
        "SELECT count(*) AS n FROM suggestion_files WHERE suggestion_id = %s", (sid,)
    ).fetchone()
    if count and count["n"] >= MAX_FILES:
        raise HTTPException(400, f"at most {MAX_FILES} images per comment")
    row = conn.execute(
        "INSERT INTO suggestion_files (suggestion_id, filename, mime, data)"
        " VALUES (%s, %s, %s, %s) RETURNING id",
        (sid, filename.strip()[:120] or "image", mime, raw),
    ).fetchone()
    assert row is not None
    return {"id": int(row["id"])}


@router.delete("/api/suggestions/{sid}/files/{fid}")
def remove_file(conn: Db, sid: int, fid: int) -> dict[str, bool]:
    conn.execute(
        "DELETE FROM suggestion_files WHERE id = %s AND suggestion_id = %s"
        " AND uploaded_url IS NULL",
        (fid, sid),
    )
    return {"ok": True}


@router.post("/api/suggestions/{sid}/discard")
def discard(
    conn: Db, sid: int, reason: Annotated[str | None, Body(embed=True)] = None
) -> dict[str, bool]:
    try:
        suggestions.discard(conn, sid, reason, datetime.now(UTC))
    except suggestions.SuggestionError as e:
        raise HTTPException(404 if str(e).startswith("no suggestion") else 400, str(e)) from e
    return {"ok": True}
