"""Dictation (voice-dictation spec): upload, background transcription, forms, save, history."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from kb import dictation
from kb.api.deps import get_conn
from kb.api.routes_requests import background
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


def _view(r: dict[str, Any]) -> dict[str, Any]:
    first = (r["transcript"] or "").strip().split("\n", 1)[0]
    return {
        "id": r["id"],
        "status": r["status"],
        "seconds": float(r["seconds"]),
        "first_line": first[:120],
        "transcript": r["transcript"],
        "forms": r["forms"],
        "error": r["error"],
        "cost_usd": float(r["cost_usd"]),
        "saved_doc_id": r["saved_doc_id"],
        "created_at": r["created_at"].isoformat(),
    }


@router.post("/api/dictations")
async def upload(request: Request, seconds: float = 0) -> dict[str, int]:
    """The recording as the raw request body (Content-Type: the recorder's audio type)."""
    data = await request.body()
    mime = request.headers.get("content-type", "")
    state = request.app.state
    with state.connect() as conn:
        try:
            did = dictation.store_upload(conn, data, mime, seconds)
        except dictation.DictationError as e:
            raise HTTPException(400, str(e)) from e
    connect, config, transcriber = state.connect, state.config, state.transcriber

    def job() -> None:
        with connect() as c:
            dictation.transcribe(c, config, transcriber, did, datetime.now(UTC))

    background(request, job)
    return {"id": did}


@router.get("/api/dictations")
def history(conn: Db) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM dictations WHERE created_at > %s ORDER BY id DESC LIMIT 100",
        (datetime.now(UTC) - timedelta(days=dictation.KEEP_DAYS),),
    ).fetchall()
    return {"dictations": [_view(r) for r in rows]}


@router.get("/api/dictations/{did}")
def get(conn: Db, did: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM dictations WHERE id = %s", (did,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no dictation {did}")
    return _view(row)


@router.post("/api/dictations/{did}/render")
def render(
    request: Request,
    conn: Db,
    did: int,
    form: Annotated[Literal["clean", "structured"], Body(embed=True)],
) -> dict[str, Any]:
    try:
        return dictation.render(
            conn,
            request.app.state.config,
            request.app.state.dictation_llm,
            did,
            form,
            datetime.now(UTC),
        )
    except dictation.DictationError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/dictations/{did}/save")
def save(
    conn: Db,
    did: int,
    form: Annotated[Literal["verbatim", "clean", "structured"], Body(embed=True)],
    scope: Annotated[str, Body(embed=True)],
    title: Annotated[str, Body(embed=True)] = "",
    text: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, int]:
    """Saves the chosen form (or the owner's edited text) to the Library as a note."""
    from kb import library, scopes

    row = conn.execute("SELECT * FROM dictations WHERE id = %s", (did,)).fetchone()
    if row is None or not row["transcript"]:
        raise HTTPException(404, f"dictation {did} has no transcript")
    body = text
    if body is None:
        body = (
            row["transcript"] if form == "verbatim" else (row["forms"].get(form) or {}).get("text")
        )
    if not body:
        raise HTTPException(400, f"make the {form} version first")
    name = title.strip() or f"Dictation {row['created_at']:%Y-%m-%d %H:%M}"
    try:
        doc = library.add_document(
            conn,
            name,
            "note",
            [scope],
            "dictation.md",
            body.encode(),
            scopes.known(conn),
            datetime.now(UTC),
        )
    except library.LibraryError as e:
        raise HTTPException(400, str(e)) from e
    conn.execute("UPDATE dictations SET saved_doc_id = %s WHERE id = %s", (doc, did))
    return {"document_id": doc}
