"""Recorder apps and meeting notes (calendar-meetings spec; design D22).

`/api/devices/*` is called by the paired apps with `Authorization: Bearer <device token>` (no
session, no cookies, so no CSRF); a device token can only upload — it cannot read anything.
Pairing codes, the device list and notes import are owner pages (session).
"""

from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from kb import recordings
from kb.api.deps import get_conn
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]
DEVICE_PREFIX = "/api/devices/"


def device(conn: Db, authorization: Annotated[str, Header()] = "") -> dict[str, Any]:
    token = authorization.removeprefix("Bearer ").strip()
    found = recordings.device_for(conn, token, datetime.now(UTC)) if token else None
    if found is None:
        raise HTTPException(401, "unknown or revoked device")
    return found


Device = Annotated[dict[str, Any], Depends(device)]


# --- owner side (session) ---------------------------------------------------------------------


@router.post("/api/settings/devices/pair-code")
def pair_code(conn: Db) -> dict[str, str]:
    code, expires = recordings.new_pair_code(conn, datetime.now(UTC))
    return {"code": code, "expires_at": expires.isoformat()}


@router.get("/api/settings/devices")
def devices(conn: Db) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT id, name, platform, default_scope, created_at, last_seen_at FROM devices"
        " WHERE revoked_at IS NULL ORDER BY id"
    ).fetchall()
    return {
        "devices": [
            {
                **dict(r),
                "created_at": r["created_at"].isoformat(),
                "last_seen_at": r["last_seen_at"].isoformat() if r["last_seen_at"] else None,
            }
            for r in rows
        ]
    }


@router.post("/api/settings/devices/{device_id}")
def update_device(
    conn: Db, device_id: int, default_scope: Annotated[str, Body(embed=True)]
) -> dict[str, bool]:
    from kb import scopes

    if default_scope not in (*scopes.known(conn), "unsorted"):
        raise HTTPException(400, f"unknown mark {default_scope!r}")
    conn.execute("UPDATE devices SET default_scope = %s WHERE id = %s", (default_scope, device_id))
    return {"ok": True}


@router.delete("/api/settings/devices/{device_id}")
def revoke(conn: Db, device_id: int) -> dict[str, bool]:
    if not conn.execute(
        "UPDATE devices SET revoked_at = now() WHERE id = %s AND revoked_at IS NULL RETURNING id",
        (device_id,),
    ).fetchone():
        raise HTTPException(404, f"no device {device_id}")
    return {"ok": True}


class FileUpload(BaseModel):
    filename: str
    data: str = Field(description="base64")


@router.post("/api/meetings/{event_id}/notes")
def attach_notes(
    conn: Db,
    event_id: int,
    text: Annotated[str | None, Body(embed=True)] = None,
    file: Annotated[FileUpload | None, Body(embed=True)] = None,
) -> dict[str, int]:
    """Notes or a transcript recorded elsewhere, attached to a meeting (processed like any)."""
    ev = conn.execute("SELECT start_at, end_at FROM events WHERE id = %s", (event_id,)).fetchone()
    if ev is None:
        raise HTTPException(404, f"no meeting {event_id}")
    segments: list[dict[str, Any]] = []
    notes = text or ""
    try:
        if file is not None:
            try:
                data = base64.b64decode(file.data, validate=True)
            except binascii.Error as e:
                raise recordings.RecordingError("the file is not valid base64") from e
            segments, notes = recordings.notes_from_file(file.filename, data)
        if not segments and not notes.strip():
            raise recordings.RecordingError("paste the notes or attach a file")
        rid = recordings.store(
            conn,
            "notes",
            ev["start_at"],
            ev["end_at"],
            segments,
            notes,
            source="upload",
            event_id=event_id,
        )
    except recordings.RecordingError as e:
        raise HTTPException(400, str(e)) from e
    return {"recording_id": rid}


def _recording(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "kind": r["kind"],
        "source": r["source"],
        "title": r["title"],
        "event_id": r["event_id"],
        "started_at": r["started_at"].isoformat(),
        "ended_at": r["ended_at"].isoformat(),
        "segments": r["segments"],
        "notes": r["notes"],
        "scopes": list(r["scopes"]),
        "item_id": r["item_id"],
        "result": r["result"],
        "processed": r["processed_at"] is not None,
    }


@router.get("/api/recordings")
def listing(conn: Db, unscheduled: bool = False) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT * FROM recordings WHERE (NOT %s OR event_id IS NULL) AND kind <> 'voice_note'"
        " ORDER BY started_at DESC LIMIT 50",
        (unscheduled,),
    ).fetchall()
    return {"recordings": [_recording(r) for r in rows]}


@router.get("/api/recordings/{rid}")
def recording(conn: Db, rid: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM recordings WHERE id = %s", (rid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no recording {rid}")
    return _recording(row)


def for_event(conn: Conn, event_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM recordings WHERE event_id = %s ORDER BY started_at", (event_id,)
    ).fetchall()
    return [_recording(r) for r in rows]


# --- device side (bearer token) -----------------------------------------------------------------


@router.post("/api/devices/pair")
def pair(
    conn: Db,
    code: Annotated[str, Body(embed=True)],
    name: Annotated[str, Body(embed=True)],
    platform: Annotated[str, Body(embed=True)] = "",
) -> dict[str, Any]:
    try:
        device_id, token = recordings.pair(conn, code, name, platform, datetime.now(UTC))
    except recordings.RecordingError as e:
        raise HTTPException(400, str(e)) from e
    return {"device_id": device_id, "token": token}


class Segment(BaseModel):
    speaker: str = ""
    is_owner: bool = False
    start: float = 0
    end: float = 0
    text: str


class Upload(BaseModel):
    kind: Literal["call", "meeting", "voice_note"]
    started_at: datetime
    ended_at: datetime
    source: str = ""
    language: str | None = None
    segments: list[Segment] = Field(default_factory=list)
    notes: str = ""
    idempotency_key: str | None = None


@router.post("/api/devices/recordings")
def upload(conn: Db, dev: Device, body: Upload) -> dict[str, int]:
    try:
        rid = recordings.store(
            conn,
            body.kind,
            body.started_at,
            body.ended_at,
            [s.model_dump() for s in body.segments],
            body.notes,
            source=body.source,
            language=body.language,
            device=dev,
            idempotency_key=body.idempotency_key,
        )
    except recordings.RecordingError as e:
        raise HTTPException(400, str(e)) from e
    return {"recording_id": rid}
