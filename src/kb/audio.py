"""Meeting audio (calendar-meetings spec: audio kept 12 months, listening, backups; design D22).

The recorder apps announce a track (size, sha256, type), then upload it in chunks with
`Content-Range`; an interrupted upload continues from the received length. The file is written
to a temporary name and renamed once complete and verified. Audio is deleted 12 months after the
recording (the transcript stays), or earlier per recording or per project. Only the signed-in
owner can play it; it is never sent to an AI service by the web OS.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from kb.db import Conn

KEEP = timedelta(days=365)
MAX_BYTES = 2 * 1024**3  # 2 GB per track (hours of Opus)
TYPES = {"audio/ogg": "ogg", "audio/opus": "opus", "audio/mp4": "m4a", "audio/x-m4a": "m4a",
         "audio/mpeg": "mp3", "audio/wav": "wav", "audio/webm": "webm"}  # fmt: skip
TRACKS = ("owner", "others", "mixed")


class AudioError(ValueError):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


def root() -> Path:
    return Path(os.environ.get("KB_AUDIO_DIR", "/data/audio"))


def _tmp(path: str) -> Path:
    return Path(path + ".part")


def announce(
    conn: Conn,
    recording: dict[str, Any],
    track: str,
    mime: str,
    total_bytes: int,
    sha256: str,
    duration: float | None,
) -> dict[str, Any]:
    """Starts (or resumes) a track upload; returns its state."""
    if track not in TRACKS:
        raise AudioError(f"track must be one of {', '.join(TRACKS)}")
    base = mime.split(";")[0].strip().lower()
    if base not in TYPES:
        raise AudioError(f"unsupported audio type {mime!r}")
    if not 0 < total_bytes <= MAX_BYTES:
        raise AudioError("audio size must be between 1 byte and 2 GB")
    if len(sha256) != 64:
        raise AudioError("sha256 must be 64 hex characters")
    old = conn.execute(
        "SELECT * FROM recording_audio WHERE recording_id = %s AND track = %s",
        (recording["id"], track),
    ).fetchone()
    if old is not None:
        if old["sha256"] != sha256.lower() or old["total_bytes"] != total_bytes:
            if old["complete"]:
                raise AudioError("this track is already stored", 409)
            _tmp(old["path"]).unlink(missing_ok=True)  # a different file: start over
            conn.execute("DELETE FROM recording_audio WHERE id = %s", (old["id"],))
        else:
            return state(dict(old))
    rec_at = recording["started_at"]
    path = root() / f"{rec_at:%Y}" / f"{rec_at:%m}" / f"{recording['id']}-{track}.{TYPES[base]}"
    row = conn.execute(
        "INSERT INTO recording_audio (recording_id, track, mime, total_bytes, sha256,"
        " duration_seconds, path, recorded_at, expires_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING *",
        (
            recording["id"],
            track,
            base,
            total_bytes,
            sha256.lower(),
            duration,
            str(path),
            rec_at,
            rec_at + KEEP,
        ),
    ).fetchone()
    assert row is not None
    return state(dict(row))


def state(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "track": r["track"],
        "received_bytes": int(r["received_bytes"]),
        "total_bytes": int(r["total_bytes"]),
        "complete": r["complete"],
    }


def get(conn: Conn, recording_id: int, track: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM recording_audio WHERE recording_id = %s AND track = %s",
        (recording_id, track),
    ).fetchone()
    if row is None:
        raise AudioError("announce the track first", 404)
    return dict(row)


def put_chunk(conn: Conn, recording_id: int, track: str, start: int, data: bytes) -> dict[str, Any]:
    """Appends a chunk at `start`, which must equal the received length (else 409 with the
    received length, so the app continues from there). The last chunk verifies the sha256."""
    r = get(conn, recording_id, track)
    if r["complete"]:
        return state(r)
    if start != r["received_bytes"]:
        raise AudioError(f"expected the chunk at {r['received_bytes']}", 409)
    if start + len(data) > r["total_bytes"]:
        raise AudioError("the chunk goes past the announced size")
    tmp = _tmp(r["path"])
    tmp.parent.mkdir(parents=True, exist_ok=True)
    with tmp.open("ab") as f:
        f.truncate(start)  # a half-written earlier chunk is overwritten
        f.write(data)
    received = start + len(data)
    if received < r["total_bytes"]:
        conn.execute(
            "UPDATE recording_audio SET received_bytes = %s WHERE id = %s", (received, r["id"])
        )
        return {**state(r), "received_bytes": received}
    digest = hashlib.sha256()
    with tmp.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != r["sha256"]:
        tmp.unlink(missing_ok=True)
        conn.execute("UPDATE recording_audio SET received_bytes = 0 WHERE id = %s", (r["id"],))
        raise AudioError("checksum mismatch: the upload starts over", 422)
    tmp.rename(r["path"])
    conn.execute(
        "UPDATE recording_audio SET received_bytes = %s, complete = true WHERE id = %s",
        (received, r["id"]),
    )
    return {**state(r), "received_bytes": received, "complete": True}


def tracks(conn: Conn, recording_id: int) -> list[dict[str, Any]]:
    return [
        {
            "track": r["track"],
            "mime": r["mime"],
            "duration": float(r["duration_seconds"]) if r["duration_seconds"] else None,
            "bytes": int(r["total_bytes"]),
            "available": r["complete"] and r["deleted_at"] is None,
            "deleted_at": r["deleted_at"].isoformat() if r["deleted_at"] else None,
            "expires_at": r["expires_at"].isoformat(),
        }
        for r in conn.execute(
            "SELECT * FROM recording_audio WHERE recording_id = %s ORDER BY track", (recording_id,)
        ).fetchall()
    ]


def playable(conn: Conn, recording_id: int, track: str) -> tuple[Path, str]:
    r = get(conn, recording_id, track)
    if not r["complete"] or r["deleted_at"] is not None or not Path(r["path"]).exists():
        raise AudioError("no audio for this track", 404)
    return Path(r["path"]), r["mime"]


def _delete(conn: Conn, rows: list[dict[str, Any]], now: datetime) -> int:
    for r in rows:
        Path(r["path"]).unlink(missing_ok=True)
        _tmp(r["path"]).unlink(missing_ok=True)
        conn.execute("UPDATE recording_audio SET deleted_at = %s WHERE id = %s", (now, r["id"]))
    return len(rows)


def delete_recording(conn: Conn, recording_id: int, now: datetime) -> int:
    rows = conn.execute(
        "SELECT * FROM recording_audio WHERE recording_id = %s AND deleted_at IS NULL",
        (recording_id,),
    ).fetchall()
    return _delete(conn, [dict(r) for r in rows], now)


def delete_scope(conn: Conn, scope: str, now: datetime) -> int:
    rows = conn.execute(
        "SELECT a.* FROM recording_audio a JOIN recordings r ON r.id = a.recording_id"
        " WHERE %s = ANY(r.scopes) AND a.deleted_at IS NULL",
        (scope,),
    ).fetchall()
    return _delete(conn, [dict(r) for r in rows], now)


def expire(conn: Conn, now: datetime) -> int:
    """Daily: audio past its 12 months is deleted; transcripts and summaries stay."""
    rows = conn.execute(
        "SELECT * FROM recording_audio WHERE deleted_at IS NULL AND expires_at <= %s", (now,)
    ).fetchall()
    return _delete(conn, [dict(r) for r in rows], now)


def storage(conn: Conn, now: datetime) -> dict[str, Any]:
    """For Status: bytes stored, growth per month (last 3 months), deletions due in 30 days,
    and the last audio backup."""
    total = conn.execute(
        "SELECT coalesce(sum(total_bytes), 0) AS b, count(*) AS n FROM recording_audio"
        " WHERE complete AND deleted_at IS NULL"
    ).fetchone()
    recent = conn.execute(
        "SELECT coalesce(sum(total_bytes), 0) AS b FROM recording_audio WHERE complete"
        " AND created_at > %s",
        (now - timedelta(days=90),),
    ).fetchone()
    due = conn.execute(
        "SELECT count(*) AS n, min(expires_at) AS first FROM recording_audio"
        " WHERE deleted_at IS NULL AND expires_at <= %s",
        (now + timedelta(days=30),),
    ).fetchone()
    backup = conn.execute(
        "SELECT status, detail, created_at FROM backup_checks WHERE kind = 'audio'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert total is not None and recent is not None and due is not None
    return {
        "bytes": int(total["b"]),
        "files": int(total["n"]),
        "growth_bytes_per_month": int(recent["b"]) // 3,
        "deletions_next_30_days": int(due["n"]),
        "next_deletion": due["first"].isoformat() if due["first"] else None,
        "last_backup": {
            "status": backup["status"],
            "detail": backup["detail"],
            "at": backup["created_at"].isoformat(),
        }
        if backup
        else None,
    }
