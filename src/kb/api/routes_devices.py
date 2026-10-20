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

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from kb import audio, recordings
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
        "audio": r.get("audio", []),
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
    return _recording({**row, "audio": audio.tracks(conn, rid)})


def for_event(conn: Conn, event_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM recordings WHERE event_id = %s ORDER BY started_at", (event_id,)
    ).fetchall()
    return [_recording({**r, "audio": audio.tracks(conn, r["id"])}) for r in rows]


@router.get("/api/recordings/{rid}/audio/{track}", response_model=None)
def play(conn: Db, rid: int, track: str, download: bool = False) -> FileResponse:
    """The owner's playback (HTTP Range supported, for seeking); device tokens cannot read."""
    try:
        path, mime = audio.playable(conn, rid, track)
    except audio.AudioError as e:
        raise HTTPException(e.status, str(e)) from e
    return FileResponse(
        path,
        media_type=mime,
        filename=path.name if download else None,
        content_disposition_type="attachment" if download else "inline",
    )


@router.delete("/api/recordings/{rid}/audio")
def delete_audio(conn: Db, rid: int) -> dict[str, int]:
    return {"deleted": audio.delete_recording(conn, rid, datetime.now(UTC))}


@router.post("/api/scopes/{scope}/delete-audio")
def delete_scope_audio(conn: Db, scope: str) -> dict[str, int]:
    """All audio of a project (e.g. after a contract ends); transcripts stay."""
    return {"deleted": audio.delete_scope(conn, scope, datetime.now(UTC))}


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


class NewMeeting(BaseModel):
    title: str
    scope: str | None = None
    participants: list[str] = Field(default_factory=list)


class LinkBody(BaseModel):
    """`event_id: null` detaches; `new_meeting` creates a meeting outside the calendar; `scope`
    alone marks the project of a call without a meeting."""

    event_id: int | None = None
    new_meeting: NewMeeting | None = None
    scope: str | None = None


def _link(conn: Conn, rid: int, body: LinkBody) -> dict[str, Any]:
    try:
        return recordings.link(
            conn,
            rid,
            event_id=body.event_id,
            unlink="event_id" in body.model_fields_set and body.event_id is None,
            new_meeting=body.new_meeting.model_dump() if body.new_meeting else None,
            scope=body.scope,
        )
    except recordings.RecordingError as e:
        raise HTTPException(400, str(e)) from e


@router.post("/api/recordings/{rid}/link")
def link(conn: Db, rid: int, body: LinkBody) -> dict[str, Any]:
    """The owner moves a recording to another meeting, a new meeting, or marks its project."""
    if not conn.execute("SELECT 1 FROM recordings WHERE id = %s", (rid,)).fetchone():
        raise HTTPException(404, f"no recording {rid}")
    return _link(conn, rid, body)


class Upload(BaseModel):
    kind: Literal["call", "meeting", "voice_note"]
    started_at: datetime
    ended_at: datetime
    source: str = ""
    language: str | None = None
    segments: list[Segment] = Field(default_factory=list)
    notes: str = ""
    idempotency_key: str | None = None
    event_id: int | None = None  # the meeting chosen on the Mac (else matched by time)
    new_meeting: NewMeeting | None = None  # "New meeting…" for a spontaneous call


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
            event_id=body.event_id,
            idempotency_key=body.idempotency_key,
        )
        if body.new_meeting is not None and body.event_id is None:
            # a new meeting beats the automatic time match (the call was spontaneous)
            recordings.link(conn, rid, new_meeting=body.new_meeting.model_dump())
    except recordings.RecordingError as e:
        raise HTTPException(400, str(e)) from e
    return {"recording_id": rid}


@router.get("/api/devices/meetings")
def device_meetings(conn: Db, dev: Device) -> dict[str, Any]:
    """The one read a device token gets: meetings within 12 hours, titles and times only."""
    from kb import meetings

    return {"meetings": meetings.around(conn, datetime.now(UTC))}


@router.post("/api/devices/recordings/{rid}/link")
def device_link(conn: Db, dev: Device, rid: int, body: LinkBody) -> dict[str, Any]:
    _own(conn, dev, rid)
    return _link(conn, rid, body)


def _own(conn: Conn, dev: dict[str, Any], rid: int) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM recordings WHERE id = %s AND device_id = %s", (rid, dev["id"])
    ).fetchone()
    if row is None:
        raise HTTPException(404, f"no recording {rid} from this device")
    return dict(row)


def _audio_error(e: audio.AudioError, conn: Conn, rid: int, track: str) -> JSONResponse:
    body: dict[str, Any] = {"detail": str(e)}
    headers = {}
    if e.status == 409:
        try:
            got = audio.state(audio.get(conn, rid, track))
            body.update(got)
            headers["Upload-Offset"] = str(got["received_bytes"])
        except audio.AudioError:
            pass
    return JSONResponse(body, status_code=e.status, headers=headers)


class Announce(BaseModel):
    mime: str
    total_bytes: int
    sha256: str
    duration_seconds: float | None = None


@router.post("/api/devices/recordings/{rid}/audio/{track}", response_model=None)
def announce(conn: Db, dev: Device, rid: int, track: str, body: Announce) -> Any:
    rec = _own(conn, dev, rid)
    try:
        return audio.announce(
            conn, rec, track, body.mime, body.total_bytes, body.sha256, body.duration_seconds
        )
    except audio.AudioError as e:
        return _audio_error(e, conn, rid, track)


@router.head("/api/devices/recordings/{rid}/audio/{track}")
def received(conn: Db, dev: Device, rid: int, track: str) -> Response:
    """How much of the track arrived (Upload-Offset), so an interrupted upload continues."""
    _own(conn, dev, rid)
    try:
        st = audio.state(audio.get(conn, rid, track))
    except audio.AudioError as e:
        raise HTTPException(e.status, str(e)) from e
    return Response(
        headers={
            "Upload-Offset": str(st["received_bytes"]),
            "Upload-Length": str(st["total_bytes"]),
            "Upload-Complete": "1" if st["complete"] else "0",
        }
    )


@router.put("/api/devices/recordings/{rid}/audio/{track}", response_model=None)
async def chunk(request: Request, rid: int, track: str) -> Any:
    """One chunk with `Content-Range: bytes <start>-<end>/<total>` (8 MB recommended)."""
    from starlette.concurrency import run_in_threadpool

    data = await request.body()
    rng = request.headers.get("content-range", "")
    try:
        unit, _, spec = rng.partition(" ")
        span, _, _total = spec.partition("/")
        start, _, end = span.partition("-")
        if unit != "bytes" or int(end) - int(start) + 1 != len(data):
            raise ValueError
    except ValueError:
        return JSONResponse({"detail": "Content-Range must match the body"}, status_code=400)
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()

    def work() -> Any:
        with request.app.state.connect() as conn:
            dev = recordings.device_for(conn, token, datetime.now(UTC)) if token else None
            if dev is None:
                return JSONResponse({"detail": "unknown or revoked device"}, status_code=401)
            try:
                _own(conn, dev, rid)
                return audio.put_chunk(conn, rid, track, int(start), data)
            except HTTPException as e:
                return JSONResponse({"detail": e.detail}, status_code=e.status_code)
            except audio.AudioError as e:
                return _audio_error(e, conn, rid, track)

    return await run_in_threadpool(work)


@router.post("/api/devices/dictations", response_model=None)
async def device_dictation(
    request: Request,
    form: Literal["verbatim", "clean", "structured"] = "verbatim",
    seconds: float = 0,
) -> Any:
    """Dictated audio (raw body, Content-Type = the recorder's audio type) → text from OpenAI,
    as said, cleaned or structured. The device reads back only this text."""
    from starlette.concurrency import run_in_threadpool

    from kb import dictation

    data = await request.body()
    mime = request.headers.get("content-type", "")
    token = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    state = request.app.state

    def work() -> Any:
        with state.connect() as conn:
            dev = recordings.device_for(conn, token, datetime.now(UTC)) if token else None
            if dev is None:
                return JSONResponse({"detail": "unknown or revoked device"}, status_code=401)
            try:
                return dictation.for_device(
                    conn,
                    state.config,
                    state.transcriber,
                    state.dictation_llm,
                    int(dev["id"]),
                    data,
                    mime,
                    seconds,
                    form,
                    datetime.now(UTC),
                )
            except dictation.DictationError as e:
                return JSONResponse({"detail": str(e)}, status_code=422)

    return await run_in_threadpool(work)


class TranscribeRequest(BaseModel):
    speakers: bool = False
    dry_run: bool = False  # only the cost estimate


@router.post("/api/devices/recordings/{rid}/transcribe")
def transcribe(conn: Db, dev: Device, rid: int, body: TranscribeRequest) -> dict[str, Any]:
    """Cloud transcription of an uploaded recording (the Mac's "Cloud" mode or "Separate
    speakers"); `dry_run` returns the estimate shown before the owner confirms."""
    from kb import settings_store, transcription

    rec = _own(conn, dev, rid)
    provider = "openai-diarize" if body.speakers else settings_store.load(conn).calls_provider
    seconds = conn.execute(
        "SELECT coalesce(sum(duration_seconds), 0) AS s FROM recording_audio"
        " WHERE recording_id = %s AND complete AND deleted_at IS NULL"
        + (" AND track <> 'owner'" if body.speakers else ""),
        (rid,),
    ).fetchone()
    estimate = transcription.estimate_usd(provider, float(seconds["s"] if seconds else 0))
    if body.dry_run:
        return {"provider": provider, "estimated_usd": estimate}
    if not transcription.available(provider):
        raise HTTPException(400, f"the call provider {provider!r} is not configured on the server")
    try:
        job = transcription.request(conn, rec, body.speakers)
    except transcription.TranscriptionError as e:
        raise HTTPException(400, str(e)) from e
    return {"job_id": job, "provider": provider, "estimated_usd": estimate}
