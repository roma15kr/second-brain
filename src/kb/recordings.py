"""Calls, meetings and notes delivered by the recorder apps or attached by hand
(calendar-meetings spec; web-os-v1 design D20, D22).

A transcript is matched to the calendar event it overlaps by at least half of its length, else
it is an unscheduled call or meeting named after its date and the people recognised from the
speakers. Each recording becomes a searchable `meeting` item. Processing (routines) produces a
summary, decisions and actions: the owner's own actions become loops, everyone else's become
ClickUp task drafts in the approval queue. Voice notes become Library notes.
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
import secrets as pysecrets
from datetime import datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from kb import distill, settings_store
from kb.db import Conn
from kb.redact import redact_text

log = logging.getLogger(__name__)

SOURCE_ID = "recordings"
PAIR_MINUTES = 10
MATCH_SHARE = 0.5
KINDS = ("call", "meeting", "voice_note", "notes")


class RecordingError(ValueError):
    pass


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- devices ----------------------------------------------------------------------------------


def new_pair_code(conn: Conn, now: datetime) -> tuple[str, datetime]:
    """A one-time code for pairing a recorder app (valid 10 minutes, single use)."""
    code = "".join(pysecrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    expires = now + timedelta(minutes=PAIR_MINUTES)
    conn.execute(
        "INSERT INTO device_pair_codes (code_hash, expires_at) VALUES (%s, %s)",
        (_hash(code), expires),
    )
    return code, expires


def pair(conn: Conn, code: str, name: str, platform: str, now: datetime) -> tuple[int, str]:
    row = conn.execute(
        "UPDATE device_pair_codes SET used_at = %s WHERE code_hash = %s AND used_at IS NULL"
        " AND expires_at > %s RETURNING code_hash",
        (now, _hash(code.strip().upper()), now),
    ).fetchone()
    if row is None:
        raise RecordingError("the pairing code is wrong, used or expired")
    token = pysecrets.token_urlsafe(32)
    dev = conn.execute(
        "INSERT INTO devices (name, platform, token_hash, last_seen_at) VALUES (%s, %s, %s, %s)"
        " RETURNING id",
        ((name.strip() or "Recorder")[:80], platform[:40], _hash(token), now),
    ).fetchone()
    assert dev is not None
    return int(dev["id"]), token


def device_for(conn: Conn, token: str, now: datetime) -> dict[str, Any] | None:
    row = conn.execute(
        "UPDATE devices SET last_seen_at = %s WHERE token_hash = %s AND revoked_at IS NULL"
        " RETURNING *",
        (now, _hash(token)),
    ).fetchone()
    return dict(row) if row else None


# --- transcripts ------------------------------------------------------------------------------


def transcript_text(segments: list[dict[str, Any]], notes: str = "") -> str:
    lines = []
    for s in segments:
        start = float(s.get("start") or 0)
        stamp = f"[{int(start // 60):02d}:{int(start % 60):02d}]"
        lines.append(f"{stamp} {s.get('speaker') or '?'}: {s.get('text', '')}")
    if notes.strip():
        lines += ["", "NOTES:", notes.strip()]
    return "\n".join(lines)


_CUE_TIME = re.compile(r"(\d{1,2}:)?\d{1,2}:\d{2}[.,]\d{3}\s*-->")


def _seconds(stamp: str) -> float:
    parts = stamp.replace(",", ".").split(":")
    return sum(float(p) * 60**i for i, p in enumerate(reversed(parts)))


def parse_cues(text: str) -> list[dict[str, Any]]:
    """WebVTT / SRT cues → segments (speaker from `<v Name>` or a leading `Name:`)."""
    segments: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        lines = [x for x in block.strip().split("\n") if x.strip()]
        times = next((x for x in lines if _CUE_TIME.search(x)), None)
        if times is None:
            continue
        body = " ".join(lines[lines.index(times) + 1 :]).strip()
        speaker = ""
        if m := re.match(r"<v\s+([^>]+)>(.*)", body):
            speaker, body = m.group(1).strip(), re.sub(r"</v>", "", m.group(2)).strip()
        elif m := re.match(r"([^:]{1,40}):\s+(.*)", body):
            speaker, body = m.group(1).strip(), m.group(2).strip()
        start = _seconds(times.split("-->")[0].strip())
        end = _seconds(times.split("-->")[1].strip().split()[0])
        if body:
            segments.append(
                {"speaker": speaker, "is_owner": False, "start": start, "end": end, "text": body}
            )
    return segments


def notes_from_file(filename: str, data: bytes) -> tuple[list[dict[str, Any]], str]:
    """(segments, notes) from an attached .txt/.md/.vtt/.srt/.docx file."""
    name = filename.lower()
    if name.endswith(".docx"):
        import docx

        doc = docx.Document(io.BytesIO(data))
        return [], "\n".join(p.text for p in doc.paragraphs)
    text = data.decode("utf-8", errors="replace")
    if name.endswith((".vtt", ".srt")):
        segs = parse_cues(text)
        if not segs:
            raise RecordingError("no subtitle cues found in the file")
        return segs, ""
    if name.endswith((".txt", ".md")):
        return [], text
    raise RecordingError("attach a .txt, .md, .vtt, .srt or .docx file")


def match_event(conn: Conn, started: datetime, ended: datetime) -> dict[str, Any] | None:
    """The marked calendar event overlapping at least half of the recording."""
    length = max((ended - started).total_seconds(), 1.0)
    rows = conn.execute(
        "SELECT e.id, e.title, e.attendees, c.scopes, extract(epoch FROM"
        " least(e.end_at, %s) - greatest(e.start_at, %s)) AS overlap"
        " FROM events e JOIN calendars c ON c.id = e.calendar_id"
        " WHERE c.sync AND NOT e.all_day AND NOT e.cancelled AND e.start_at < %s AND e.end_at > %s"
        " ORDER BY overlap DESC LIMIT 1",
        (ended, started, ended, started),
    ).fetchall()
    if rows and float(rows[0]["overlap"]) / length >= MATCH_SHARE:
        return dict(rows[0])
    return None


def store(
    conn: Conn,
    kind: str,
    started: datetime,
    ended: datetime,
    segments: list[dict[str, Any]],
    notes: str = "",
    source: str = "",
    language: str | None = None,
    device: dict[str, Any] | None = None,
    event_id: int | None = None,
    idempotency_key: str | None = None,
) -> int:
    if kind not in KINDS:
        raise RecordingError(f"kind must be one of {', '.join(KINDS)}")
    if ended < started:
        raise RecordingError("ended_at is before started_at")
    if idempotency_key:
        old = conn.execute(
            "SELECT id FROM recordings WHERE idempotency_key = %s", (idempotency_key,)
        ).fetchone()
        if old is not None:
            return int(old["id"])
    clean: list[dict[str, Any]] = [
        {
            "speaker": str(s.get("speaker") or "")[:80],
            "is_owner": bool(s.get("is_owner")),
            "start": float(s.get("start") or 0),
            "end": float(s.get("end") or 0),
            "text": redact_text(str(s.get("text") or "")),
        }
        for s in segments
    ]
    event = None
    if event_id is not None:
        event = conn.execute(
            "SELECT e.id, e.title, e.attendees, c.scopes FROM events e JOIN calendars c"
            " ON c.id = e.calendar_id WHERE e.id = %s",
            (event_id,),
        ).fetchone()
        if event is None:
            raise RecordingError(f"no meeting {event_id}")
    elif kind in ("call", "meeting"):
        event = match_event(conn, started, ended)
    speakers = sorted({s["speaker"] for s in clean if s["speaker"] and not s["is_owner"]})
    if event is not None:
        title, scopes = event["title"] or "Meeting", list(event["scopes"]) or ["unsorted"]
    else:
        from kb.routines import KYIV

        label = {"call": "Call", "meeting": "Meeting", "voice_note": "Voice note", "notes": "Notes"}
        with_whom = f" with {', '.join(speakers[:3])}" if speakers else ""
        title = f"{label[kind]}{with_whom} · {started.astimezone(KYIV):%Y-%m-%d %H:%M}"
        scopes = [device["default_scope"]] if device else ["unsorted"]
    row = conn.execute(
        "INSERT INTO recordings (device_id, event_id, kind, source, title, started_at, ended_at,"
        " language, segments, notes, idempotency_key, scopes)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            device["id"] if device else None,
            event["id"] if event else None,
            kind,
            source[:60],
            title[:200],
            started,
            ended,
            language,
            Jsonb(clean),
            redact_text(notes),
            idempotency_key,
            scopes,
        ),
    ).fetchone()
    assert row is not None
    rid = int(row["id"])
    _index(conn, rid)
    return rid


def _identity_keys(conn: Conn, rec: dict[str, Any]) -> list[str]:
    """People in a recording: the event's attendees, else speakers matching a person's name."""
    from kb import people

    keys: list[str] = []
    if rec["event_id"]:
        ev = conn.execute(
            "SELECT attendees FROM events WHERE id = %s", (rec["event_id"],)
        ).fetchone()
        keys += [
            people.email_key(a["email"]) for a in (ev["attendees"] if ev else []) if a.get("email")
        ]
    for s in {x["speaker"] for x in rec["segments"] if x["speaker"] and not x["is_owner"]}:
        for p in people.find(conn, s, 2):
            if (p["display_name"] or "").lower() == s.lower():
                keys += people.keys_of(conn, p["id"])
    return list(dict.fromkeys(keys))


def _index(conn: Conn, rid: int) -> None:
    """The recording as a searchable item (kind `meeting`)."""
    rec = conn.execute("SELECT * FROM recordings WHERE id = %s", (rid,)).fetchone()
    assert rec is not None
    text = transcript_text(rec["segments"], rec["notes"])
    speakers = sorted({s["speaker"] for s in rec["segments"] if s["speaker"]})
    summary = (rec["result"] or {}).get("summary")
    link = f"/meetings/{rec['event_id']}" if rec["event_id"] else f"/recordings/{rid}"
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text, summary,
                           participants, occurred_at, last_activity_at, locator, identity_keys,
                           metadata, content_hash)
        VALUES (%s, %s, 'meeting', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, source_item_key) DO UPDATE SET scopes = EXCLUDED.scopes,
            title = EXCLUDED.title, raw_text = EXCLUDED.raw_text, summary = EXCLUDED.summary,
            participants = EXCLUDED.participants, identity_keys = EXCLUDED.identity_keys,
            metadata = EXCLUDED.metadata, content_hash = EXCLUDED.content_hash, updated_at = now()
        RETURNING id
        """,
        (
            SOURCE_ID,
            f"rec:{rid}",
            list(rec["scopes"]),
            rec["title"],
            text,
            summary,
            speakers,
            rec["started_at"],
            rec["ended_at"],
            link,
            _identity_keys(conn, dict(rec)),
            Jsonb({"recording_id": rid, "event_id": rec["event_id"], "kind": rec["kind"]}),
            distill.content_hash(rec["title"], text),
        ),
    ).fetchone()
    assert row is not None
    conn.execute("UPDATE recordings SET item_id = %s WHERE id = %s", (row["id"], rid))


# --- processing -------------------------------------------------------------------------------

SYSTEM = """From a meeting transcript or notes, write: a short summary (3-5 sentences); the
decisions made; and the action items, each with the person responsible (`owner`, as named in the
text; "me" when it is the owner — the speaker marked OWNER, or "I" in the owner's notes), whether it
is the owner (`is_me`), and `due` in the words used (e.g. "Friday") or null. Write in the main
language of the meeting. Use only what was said."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "decisions": {"type": "array", "items": {"type": "string"}},
        "actions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "owner": {"type": "string"},
                    "is_me": {"type": "boolean"},
                    "due": {"type": ["string", "null"]},
                },
                "required": ["text", "owner", "is_me", "due"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "decisions", "actions"],
    "additionalProperties": False,
}

WEEKDAYS = {
    # uk, ru, en → Monday = 0
    "понеділ": 0, "вівтор": 1, "серед": 2, "четвер": 3, "пʼятниц": 4, "п'ятниц": 4, "субот": 5,
    "неділ": 6, "понедельник": 0, "вторник": 1, "сред": 2, "пятниц": 4, "воскресен": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5,
    "sunday": 6,
}  # fmt: skip


def resolve_due(words: str | None, day: datetime) -> str | None:
    """'Friday' / 'до пʼятниці' → the next such date after the meeting; anything else → None
    (the owner sets it when approving)."""
    if not words:
        return None
    w = words.lower()
    for stem, wd in WEEKDAYS.items():
        if stem in w:
            ahead = (wd - day.weekday()) % 7 or 7
            return (day.date() + timedelta(days=ahead)).isoformat()
    if m := re.search(r"\d{4}-\d{2}-\d{2}", w):
        return m.group(0)
    return None


def process(conn: Conn, config: Any, llm: Any, rid: int, now: datetime) -> dict[str, Any]:
    from kb import loops
    from kb.assistant import actions, suggestions
    from kb.routines import KYIV

    rec = conn.execute("SELECT * FROM recordings WHERE id = %s", (rid,)).fetchone()
    assert rec is not None
    text = transcript_text(
        [
            {**s, "speaker": f"{s['speaker']} (OWNER)" if s["is_owner"] else s["speaker"]}
            for s in rec["segments"]
        ],
        rec["notes"],
    )
    model = config.llm.briefs_model()
    data, usage = llm.structured(
        model, SYSTEM, f"TITLE: {rec['title']}\n{text}"[:60_000], SCHEMA, "meeting", "low"
    )
    distill.record_usage(conn, "assistant", model, "meeting_notes", usage)
    day = rec["started_at"].astimezone(KYIV)
    for a in data.get("actions", []):
        due = resolve_due(a.get("due"), day)
        if a.get("is_me"):
            lid = loops.add_manual(
                conn,
                a["text"],
                now,
                due=datetime.fromisoformat(due).date() if due else None,
                counterpart=rec["title"],
                scopes=list(rec["scopes"]),
            )
            conn.execute(
                "UPDATE loops SET kind = 'i_owe', item_id = %s WHERE id = %s", (rec["item_id"], lid)
            )
            a["loop_id"] = lid
        else:
            who = actions.resolve_assignee(conn, a.get("owner") or "")
            target = actions.resolve_list(conn, None)
            if target is None:
                continue  # no ClickUp list for drafts: the action stays in the summary only
            a["suggestion_id"] = suggestions.propose(
                conn,
                "task",
                {
                    "list_id": target[0],
                    "list": target[1],
                    "name": a["text"],
                    "description": f"From the meeting “{rec['title']}”",
                    "assignee_emails": [who[1]] if who else [],
                    "assignee_name": who[0] if who else (a.get("owner") or ""),
                    "due_date": due,
                    "source_item_id": rec["item_id"],
                },
                reason=f"From the meeting “{rec['title']}”",
                refs=[f"item:{rec['item_id']}"] if rec["item_id"] else [],
                scopes=list(rec["scopes"]),
                item_id=rec["item_id"],
            )
    conn.execute(
        "UPDATE recordings SET result = %s, processed_at = %s WHERE id = %s",
        (Jsonb(data), now, rid),
    )
    _index(conn, rid)
    return data


def process_due(conn: Conn, config: Any, llm: Any, now: datetime) -> int:
    """Unprocessed recordings with content, a few per cycle, within the AI budget."""
    if llm is None:
        return 0
    if distill.month_spend_usd(conn, now.date()) >= settings_store.budget_usd(conn, config):
        return 0
    done = 0
    for r in conn.execute(
        "SELECT id, kind FROM recordings WHERE processed_at IS NULL"
        " AND (jsonb_array_length(segments) > 0 OR notes <> '') ORDER BY created_at LIMIT 3"
    ).fetchall():
        try:
            if r["kind"] == "voice_note":
                _voice_note(conn, int(r["id"]), now)
            else:
                process(conn, config, llm, int(r["id"]), now)
            done += 1
        except Exception:
            log.exception("recording %s not processed", r["id"])
            conn.execute("UPDATE recordings SET processed_at = %s WHERE id = %s", (now, r["id"]))
    return done


def _voice_note(conn: Conn, rid: int, now: datetime) -> None:
    """A voice note becomes a Library note marked with the device's default mark."""
    from kb import library, scopes

    rec = conn.execute("SELECT * FROM recordings WHERE id = %s", (rid,)).fetchone()
    assert rec is not None
    body = " ".join(s["text"] for s in rec["segments"]) or rec["notes"]
    library.add_document(
        conn,
        rec["title"],
        "note",
        list(rec["scopes"]),
        "voice-note.md",
        body.encode(),
        (*scopes.known(conn), "unsorted"),
        now,
    )
    conn.execute("UPDATE recordings SET processed_at = %s WHERE id = %s", (now, rid))
