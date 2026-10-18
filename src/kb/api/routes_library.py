"""Library: the personal base (personal-base spec). Files come as base64 in JSON (≤ 20 MB)."""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel

from kb import library, scopes
from kb.api.deps import get_conn
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


class Upload(BaseModel):
    filename: str
    content_b64: str


def _decode(upload: Upload) -> bytes:
    try:
        return base64.b64decode(upload.content_b64, validate=True)
    except (binascii.Error, ValueError) as e:
        raise HTTPException(400, "the file content is not valid base64") from e


def _valid(conn: Conn) -> tuple[str, ...]:
    return scopes.known(conn)


@router.get("/api/library")
def listing(conn: Db) -> dict[str, Any]:
    return {"documents": library.listing(conn), "kinds": list(library.KINDS)}


@router.post("/api/library")
def add(
    conn: Db,
    kind: Annotated[str, Body(embed=True)],
    scopes_: Annotated[list[str], Body(embed=True, alias="scopes")],
    title: Annotated[str, Body(embed=True)] = "",
    file: Annotated[Upload | None, Body(embed=True)] = None,
    text: Annotated[str | None, Body(embed=True)] = None,
    ai_allowed: Annotated[bool | None, Body(embed=True)] = None,
) -> dict[str, int]:
    """A file upload, or a note written in the app (`text`)."""
    if file is None and text is None:
        raise HTTPException(400, "send a file or the note text")
    filename, data = (file.filename, _decode(file)) if file else ("note.md", (text or "").encode())
    if file is None and not title.strip():
        raise HTTPException(400, "a note needs a title")
    try:
        doc_id = library.add_document(
            conn, title, kind, scopes_, filename, data, _valid(conn), datetime.now(UTC), ai_allowed
        )
    except library.LibraryError as e:
        raise HTTPException(400, str(e)) from e
    return {"id": doc_id}


@router.get("/api/library/{doc_id}")
def document(conn: Db, doc_id: int) -> dict[str, Any]:
    try:
        doc = library.get(conn, doc_id)
    except library.LibraryError as e:
        raise HTTPException(404, str(e)) from e
    versions = conn.execute(
        "SELECT id, filename, size, created_at FROM document_versions WHERE document_id = %s"
        " ORDER BY id DESC",
        (doc_id,),
    ).fetchall()
    latest = library.latest_version(conn, doc_id)
    return {
        "id": doc["id"],
        "title": doc["title"],
        "kind": doc["kind"],
        "core": doc["kind"] in library.CORE_KINDS,
        "scopes": list(doc["scopes"]),
        "ai_allowed": doc["ai_allowed"],
        "text": (latest or {}).get("text", "")[:200_000],
        "versions": [
            {
                "id": v["id"],
                "filename": v["filename"],
                "size": v["size"],
                "created_at": v["created_at"].isoformat(),
            }
            for v in versions
        ],
    }


@router.get("/api/library/{doc_id}/versions/{version_id}")
def version_text(conn: Db, doc_id: int, version_id: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT filename, text, created_at FROM document_versions WHERE id = %s"
        " AND document_id = %s",
        (version_id, doc_id),
    ).fetchone()
    if row is None:
        raise HTTPException(404, "no such version")
    return {
        "filename": row["filename"],
        "text": row["text"],
        "created_at": row["created_at"].isoformat(),
    }


@router.post("/api/library/{doc_id}/versions")
def new_version(
    conn: Db,
    doc_id: int,
    file: Annotated[Upload | None, Body(embed=True)] = None,
    text: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, int]:
    if file is None and text is None:
        raise HTTPException(400, "send a file or the new note text")
    filename, data = (file.filename, _decode(file)) if file else ("note.md", (text or "").encode())
    try:
        library.get(conn, doc_id)
        vid = library.add_version(conn, doc_id, filename, data, datetime.now(UTC))
    except library.LibraryError as e:
        raise HTTPException(404 if str(e).startswith("no document") else 400, str(e)) from e
    return {"version_id": vid}


@router.patch("/api/library/{doc_id}")
def update(
    conn: Db,
    doc_id: int,
    title: Annotated[str | None, Body(embed=True)] = None,
    kind: Annotated[str | None, Body(embed=True)] = None,
    scopes_: Annotated[list[str] | None, Body(embed=True, alias="scopes")] = None,
    ai_allowed: Annotated[bool | None, Body(embed=True)] = None,
) -> dict[str, bool]:
    try:
        library.update(conn, doc_id, _valid(conn), title, kind, scopes_, ai_allowed)
    except library.LibraryError as e:
        raise HTTPException(404 if str(e).startswith("no document") else 400, str(e)) from e
    return {"ok": True}


@router.delete("/api/library/{doc_id}")
def remove(conn: Db, doc_id: int) -> dict[str, bool]:
    library.delete(conn, doc_id)
    return {"ok": True}
