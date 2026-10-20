"""Transcription costs (and, for calls, cloud providers) — mac-recorder-v1.

Every paid transcription is written to `transcription_costs`, which counts towards the monthly
AI budget together with the language-model usage.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Protocol

from kb.db import Conn


def record_cost(
    conn: Conn,
    kind: str,
    provider: str,
    model: str,
    seconds: float,
    usd: float,
    day: date | None = None,
) -> None:
    conn.execute(
        "INSERT INTO transcription_costs (day, kind, provider, model, seconds, usd)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (day or datetime.now().date(), kind, provider, model, seconds, usd),
    )


def month_spend_usd(conn: Conn, today: date) -> float:
    row = conn.execute(
        "SELECT coalesce(sum(usd), 0) AS usd FROM transcription_costs"
        " WHERE day >= %s AND day <= %s",
        (today.replace(day=1), today),
    ).fetchone()
    return float(row["usd"]) if row else 0.0


def month_by_kind(conn: Conn, today: date) -> dict[str, float]:
    rows = conn.execute(
        "SELECT kind, coalesce(sum(usd), 0) AS usd FROM transcription_costs"
        " WHERE day >= %s AND day <= %s GROUP BY kind",
        (today.replace(day=1), today),
    ).fetchall()
    out = {"dictation": 0.0, "call": 0.0}
    out.update({r["kind"]: round(float(r["usd"]), 4) for r in rows})
    return out


# --- cloud transcription of call tracks (mac-recorder-v1 D4) -----------------------------------
#
# Interleaving the "me" and "others" tracks needs timestamps, so only providers that return
# timed segments are used for calls: OpenAI diarize (also separates speakers), OpenAI Whisper,
# and Groq Whisper large-v3-turbo (OpenAI-compatible API; only when GROQ_API_KEY is set).


MAX_BYTES = 25 * 1024 * 1024  # the providers' upload limit (~100 min at the Mac's 32 kbps)
GROQ_BASE_URL = "https://api.groq.com/openai/v1"


@dataclass(frozen=True)
class Provider:
    name: str
    vendor: str  # openai | groq
    model: str
    usd_per_minute: float
    response_format: str


PROVIDERS = {
    "openai-diarize": Provider(
        "openai-diarize", "openai", "gpt-4o-transcribe-diarize", 0.006, "diarized_json"
    ),
    "openai-whisper": Provider("openai-whisper", "openai", "whisper-1", 0.006, "verbose_json"),
    "groq": Provider("groq", "groq", "whisper-large-v3-turbo", 0.04 / 60, "verbose_json"),
}


class TranscriptionError(RuntimeError):
    pass


class SegmentApi(Protocol):
    def segments(self, provider: Provider, path: Path) -> list[dict[str, Any]]:
        """[{start, end, text, speaker?}] for one audio file."""
        ...


class CloudApi:
    """OpenAI and Groq through the OpenAI SDK (Groq is OpenAI-compatible)."""

    def segments(self, provider: Provider, path: Path) -> list[dict[str, Any]]:
        from openai import OpenAI

        if provider.vendor == "groq":
            key = os.environ.get("GROQ_API_KEY")
            if not key:
                raise TranscriptionError("Groq is not configured (GROQ_API_KEY)")
            client = OpenAI(api_key=key, base_url=GROQ_BASE_URL)
        else:
            client = OpenAI()
        extra: dict[str, Any] = {"response_format": provider.response_format}
        if provider.response_format == "diarized_json":
            extra["chunking_strategy"] = "auto"
        with path.open("rb") as f:
            r = client.audio.transcriptions.create(model=provider.model, file=f, **extra)
        data = r.model_dump() if hasattr(r, "model_dump") else dict(r)
        return [
            {
                "start": float(s.get("start") or 0),
                "end": float(s.get("end") or 0),
                "text": str(s.get("text") or "").strip(),
                "speaker": s.get("speaker"),
            }
            for s in data.get("segments") or []
            if str(s.get("text") or "").strip()
        ]


def available(name: str) -> bool:
    p = PROVIDERS.get(name)
    return p is not None and (p.vendor != "groq" or bool(os.environ.get("GROQ_API_KEY")))


def estimate_usd(provider: str, seconds: float) -> float:
    return round(seconds / 60 * PROVIDERS[provider].usd_per_minute, 4)


def request(conn: Conn, recording: dict[str, Any], speakers: bool) -> int:
    """Queue cloud transcription of a recording whose tracks are fully uploaded."""
    tracks = conn.execute(
        "SELECT track, total_bytes, complete FROM recording_audio WHERE recording_id = %s"
        " AND deleted_at IS NULL",
        (recording["id"],),
    ).fetchall()
    ready = [t for t in tracks if t["complete"]]
    if not ready:
        raise TranscriptionError("upload the audio first")
    if any(int(t["total_bytes"]) > MAX_BYTES for t in ready):
        raise TranscriptionError(
            "a track is over 25 MB (about 100 minutes); transcribe it on the Mac"
        )
    row = conn.execute(
        "INSERT INTO transcription_jobs (recording_id, speakers) VALUES (%s, %s) RETURNING id",
        (recording["id"], speakers),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def run_jobs(conn: Conn, now: datetime, api: SegmentApi | None = None, limit: int = 2) -> int:
    """Routines service: transcribe queued recordings, replace their segments, record the cost
    and send them back through processing (summary, loops, task drafts)."""
    from kb import recordings, settings_store

    api = api or CloudApi()
    done = 0
    for job in conn.execute(
        "SELECT * FROM transcription_jobs WHERE status = 'queued' ORDER BY created_at LIMIT %s",
        (limit,),
    ).fetchall():
        conn.execute("UPDATE transcription_jobs SET status = 'running' WHERE id = %s", (job["id"],))
        try:
            usd = _transcribe_recording(
                conn,
                api,
                int(job["recording_id"]),
                bool(job["speakers"]),
                settings_store.load(conn).calls_provider,
                now,
            )
        except Exception as e:
            conn.execute(
                "UPDATE transcription_jobs SET status = 'failed', error = %s, finished_at = %s"
                " WHERE id = %s",
                (str(e)[:300], now, job["id"]),
            )
            continue
        conn.execute(
            "UPDATE transcription_jobs SET status = 'done', usd = %s, finished_at = %s"
            " WHERE id = %s",
            (usd, now, job["id"]),
        )
        recordings.reprocess(conn, int(job["recording_id"]))
        done += 1
    return done


def _transcribe_recording(
    conn: Conn, api: SegmentApi, rid: int, speakers: bool, provider_name: str, now: datetime
) -> float:
    from psycopg.types.json import Jsonb

    from kb.redact import redact_text

    rec = conn.execute("SELECT * FROM recordings WHERE id = %s", (rid,)).fetchone()
    assert rec is not None
    if not available(provider_name):
        raise TranscriptionError(f"the call provider {provider_name!r} is not configured")
    tracks = {
        t["track"]: t
        for t in conn.execute(
            "SELECT * FROM recording_audio WHERE recording_id = %s AND complete"
            " AND deleted_at IS NULL",
            (rid,),
        ).fetchall()
    }
    plan: dict[str, Provider] = {}
    if speakers:  # only "others" is re-done, with speaker separation; "me" stays as it is
        if "others" not in tracks and "mixed" not in tracks:
            raise TranscriptionError("there is no others track to separate")
        plan["others" if "others" in tracks else "mixed"] = PROVIDERS["openai-diarize"]
    else:
        plan = {t: PROVIDERS[provider_name] for t in tracks}
    keep = [s for s in rec["segments"] if speakers and s.get("is_owner")]
    new: list[dict[str, Any]] = []
    usd = 0.0
    for track, provider in plan.items():
        segs = api.segments(provider, Path(tracks[track]["path"]))
        seconds = float(tracks[track]["duration_seconds"] or (segs[-1]["end"] if segs else 0))
        cost = estimate_usd(provider.name, seconds)
        record_cost(conn, "call", provider.vendor, provider.model, seconds, cost, now.date())
        usd += cost
        owner = track == "owner"
        for s in segs:
            label = "me" if owner else (f"others {s['speaker']}" if s.get("speaker") else "others")
            new.append(
                {
                    "speaker": label,
                    "is_owner": owner,
                    "start": s["start"],
                    "end": s["end"],
                    "text": redact_text(s["text"]),
                }
            )
    merged = sorted(keep + new, key=lambda s: float(s["start"]))
    conn.execute("UPDATE recordings SET segments = %s WHERE id = %s", (Jsonb(merged), rid))
    return usd
