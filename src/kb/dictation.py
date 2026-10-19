"""Dictation in the web OS (voice-dictation spec; assistant-command-v1 design D7-D8).

The browser uploads the recording; it is transcribed in the background and the audio is deleted
as soon as the (redacted) transcript is stored. A failed transcription keeps the audio for retries
for 7 days, then deletes it. Clean and Structured forms are made on demand and cached; both are
checked for faithfulness (Clean must keep the wording; Structured may not invent dates).
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from psycopg.types.json import Jsonb

from kb import distill
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm
from kb.redact import redact_text

log = logging.getLogger(__name__)

AI_SOURCE = "assistant"
MAX_BYTES = 25 * 1024 * 1024  # OpenAI's upload limit; ~15 min at 64 kbps AAC
MAX_SECONDS = 15 * 60
KEEP_FAILED_DAYS = 7
KEEP_DAYS = 90
MAX_ATTEMPTS = 5
RETRY_AFTER = timedelta(minutes=10)
CLEAN_MAX_LOSS = 0.15  # Clean may drop at most this share of the transcript's content words
EXT = {
    "audio/webm": "webm",
    "audio/mp4": "m4a",
    "audio/ogg": "ogg",
    "audio/mpeg": "mp3",
    "audio/wav": "wav",
    "audio/x-m4a": "m4a",
}
FORMS = ("clean", "structured")


class DictationError(ValueError):
    pass


def directory() -> Path:
    return Path(os.environ.get("KB_DICTATION_DIR", "/data/dictations"))


class Transcriber(Protocol):
    def transcribe(self, path: Path, model: str) -> str: ...


class OpenAITranscriber:
    def __init__(self) -> None:
        from openai import OpenAI

        self.client = OpenAI()

    def transcribe(self, path: Path, model: str) -> str:
        with path.open("rb") as f:
            r = self.client.audio.transcriptions.create(model=model, file=f)
        return str(r.text)


def default_transcriber() -> Transcriber | None:
    return OpenAITranscriber() if os.environ.get("OPENAI_API_KEY") else None


def store_upload(conn: Conn, data: bytes, mime: str, seconds: float) -> int:
    base = mime.split(";")[0].strip().lower()
    if base not in EXT:
        raise DictationError(f"unsupported audio type {mime!r}")
    if not data:
        raise DictationError("the recording is empty")
    if len(data) > MAX_BYTES:
        raise DictationError("the recording is too large (25 MB)")
    row = conn.execute(
        "INSERT INTO dictations (mime, seconds) VALUES (%s, %s) RETURNING id",
        (base, min(max(seconds, 0.0), MAX_SECONDS)),
    ).fetchone()
    assert row is not None
    did = int(row["id"])
    directory().mkdir(parents=True, exist_ok=True)
    path = directory() / f"{did}.{EXT[base]}"
    path.write_bytes(data)
    conn.execute("UPDATE dictations SET audio_path = %s WHERE id = %s", (str(path), did))
    return did


def transcribe(
    conn: Conn, config: Config, transcriber: Transcriber | None, did: int, now: datetime
) -> None:
    row = conn.execute("SELECT * FROM dictations WHERE id = %s", (did,)).fetchone()
    if row is None or row["status"] == "done" or not row["audio_path"]:
        return
    conn.execute(
        "UPDATE dictations SET status = 'transcribing', attempts = attempts + 1,"
        " attempted_at = %s WHERE id = %s",
        (now, did),
    )
    try:
        if transcriber is None:
            raise RuntimeError("transcription needs OPENAI_API_KEY on the server")
        text = transcriber.transcribe(Path(row["audio_path"]), config.llm.transcribe_model)
    except Exception as e:
        log.warning("dictation %s not transcribed: %s", did, e)
        conn.execute(
            "UPDATE dictations SET status = 'failed', error = %s WHERE id = %s", (str(e)[:300], did)
        )
        return
    cost = float(row["seconds"]) / 60 * config.llm.transcribe_usd_per_minute
    conn.execute(
        "UPDATE dictations SET status = 'done', transcript = %s, error = NULL, cost_usd = %s,"
        " audio_path = NULL WHERE id = %s",
        (redact_text(text.strip()), cost, did),
    )
    _delete_audio(row["audio_path"])


def _delete_audio(path: str | None) -> None:
    if path:
        Path(path).unlink(missing_ok=True)


def maintain(conn: Conn, config: Config, transcriber: Transcriber | None, now: datetime) -> int:
    """Retries failed transcriptions, deletes audio kept past 7 days and dictations past 90."""
    done = 0
    for r in conn.execute(
        "SELECT id, audio_path, created_at, attempts, attempted_at FROM dictations"
        " WHERE status IN ('failed', 'uploaded') AND audio_path IS NOT NULL"
    ).fetchall():
        if now - r["created_at"] > timedelta(days=KEEP_FAILED_DAYS):
            _delete_audio(r["audio_path"])
            conn.execute(
                "UPDATE dictations SET audio_path = NULL, status = 'failed',"
                " error = coalesce(error, '') || ' (audio deleted after 7 days)' WHERE id = %s",
                (r["id"],),
            )
        elif r["attempts"] < MAX_ATTEMPTS and (
            r["attempted_at"] is None or now - r["attempted_at"] >= RETRY_AFTER
        ):
            transcribe(conn, config, transcriber, int(r["id"]), now)
            done += 1
    for r in conn.execute(
        "DELETE FROM dictations WHERE created_at < %s AND saved_doc_id IS NULL"
        " RETURNING audio_path",
        (now - timedelta(days=KEEP_DAYS),),
    ).fetchall():
        _delete_audio(r["audio_path"])
    return done


# --- forms ------------------------------------------------------------------------------------

CLEAN_SYSTEM = """Clean up a dictated text: remove filler words, repetitions and false starts,
and fix punctuation and capitalisation. Do NOT reword, summarise, add, reorder or drop any
sentence; keep the speaker's words and every language they used. Return only the cleaned text."""

STRUCTURED_SYSTEM = """Turn a dictated text into a structured note in the dictation's main language
(keep names and terms in the language they were said in):
- summary: 2-3 sentences;
- sections: the content grouped under short headings, as bullet points;
- decisions: what was decided (empty if none);
- actions: what someone will do, with owner and due only when they were said explicitly; write
  `due` in the speaker's own words (e.g. "Friday", "до 23 жовтня"), not as a converted date.
Use only what was said: never invent facts, names, numbers or dates."""

CLEAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"text": {"type": "string"}},
    "required": ["text"],
    "additionalProperties": False,
}
STRUCTURED_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "heading": {"type": "string"},
                    "bullets": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["heading", "bullets"],
                "additionalProperties": False,
            },
        },
        "decisions": {"type": "array", "items": {"type": "string"}},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "owner": {"type": ["string", "null"]},
                    "due": {"type": ["string", "null"]},
                },
                "required": ["text", "owner", "due"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "sections", "decisions", "actions"],
    "additionalProperties": False,
}

_WORD = re.compile(r"\w+", re.UNICODE)
# filler words Clean is meant to remove (uk / ru / en); they do not count as content
FILLERS = frozenset(
    [
        *("значить", "власне", "отже", "короче", "типу", "тобто", "ніби", "наче"),
        *("загалом", "взагалі", "значит", "собственно", "типа", "вообще", "вроде"),
        *("basically", "actually", "literally", "like", "well", "right", "okay"),
    ]
)


def content_words(text: str) -> list[str]:
    return [w for w in _WORD.findall(text.lower()) if len(w) >= 4 and w not in FILLERS]


def clean_keeps_wording(transcript: str, clean: str) -> bool:
    """True when Clean kept at least 85% of the transcript's content words (fillers are short,
    so dropping them does not count; rewording or dropping sentences does)."""
    source = content_words(transcript)
    if not source:
        return True
    kept = set(content_words(clean))
    return sum(1 for w in source if w in kept) / len(source) >= 1 - CLEAN_MAX_LOSS


def said(value: str, transcript: str) -> bool:
    """A due date may stay only if all its words were in the dictation."""
    words = _WORD.findall(value.lower())
    spoken = set(_WORD.findall(transcript.lower()))
    return bool(words) and all(w in spoken for w in words)


def structured_markdown(s: dict[str, Any]) -> str:
    out = [s["summary"], ""]
    for sec in s["sections"]:
        out += [f"## {sec['heading']}", *[f"- {b}" for b in sec["bullets"]], ""]
    if s["decisions"]:
        out += ["## Decisions", *[f"- {d}" for d in s["decisions"]], ""]
    if s["actions"]:
        lines = []
        for a in s["actions"]:
            extra = ", ".join(x for x in (a.get("owner"), a.get("due")) if x)
            lines.append(f"- {a['text']}" + (f" ({extra})" if extra else ""))
        out += ["## Actions", *lines, ""]
    return "\n".join(out).strip()


def render(
    conn: Conn, config: Config, llm: StructuredLlm | None, did: int, form: str, now: datetime
) -> dict[str, Any]:
    if form not in FORMS:
        raise DictationError(f"unknown form {form!r}")
    row = conn.execute("SELECT * FROM dictations WHERE id = %s", (did,)).fetchone()
    if row is None:
        raise DictationError(f"no dictation {did}")
    if row["status"] != "done" or not row["transcript"]:
        raise DictationError("the dictation is not transcribed yet")
    if form in row["forms"]:
        return dict(row["forms"][form])
    if llm is None:
        raise DictationError("this needs OPENAI_API_KEY on the server")
    if distill.month_spend_usd(conn, now.date()) >= _budget(conn, config):
        raise DictationError("this month's AI budget is used up; the verbatim text is available")
    transcript = row["transcript"]
    if form == "clean":
        model = config.llm.model()
        data, usage = llm.structured(model, CLEAN_SYSTEM, transcript, CLEAN_SCHEMA, "clean", "low")
        text = str(data.get("text") or "").strip()
        result: dict[str, Any] = (
            {"text": text}
            if clean_keeps_wording(transcript, text)
            else {"text": transcript, "note": "Cleaning changed the wording, so this is verbatim."}
        )
    else:
        model = config.llm.briefs_model()
        data, usage = llm.structured(
            model, STRUCTURED_SYSTEM, transcript, STRUCTURED_SCHEMA, "structured", "low"
        )
        for a in data.get("actions", []):
            if a.get("due") and not said(a["due"], transcript):
                a["due"] = None
        result = {**data, "text": structured_markdown(data)}
    distill.record_usage(conn, AI_SOURCE, model, f"dictation_{form}", usage)
    conn.execute(
        "UPDATE dictations SET forms = forms || %s, cost_usd = cost_usd + %s WHERE id = %s",
        (Jsonb({form: result}), distill.cost_usd(model, usage), did),
    )
    return result


def _budget(conn: Conn, config: Config) -> float:
    from kb import settings_store

    return settings_store.budget_usd(conn, config)
