"""Meetings from the owner's calendars (calendar-meetings spec): listing, reminders.

A reminder is pushed `remind_minutes` before each timed meeting the owner has not declined (all-day
and cancelled events never); quiet hours apply, and an event is reminded at most once.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from kb.db import Conn

EVENT_SQL = """
    SELECT e.*, c.name AS calendar, c.remind_minutes, c.href = 'local' AS local,
           coalesce(e.scopes, c.scopes) AS scopes  -- after e.*: the meeting's own mark wins
    FROM events e
    JOIN calendars c ON c.id = e.calendar_id
    JOIN connector_accounts a ON a.id = c.account_id
    WHERE c.sync AND a.state = 'active'
"""


def to_dict(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": r["id"],
        "title": r["title"] or "(no title)",
        "start": r["start_at"].isoformat(),
        "end": r["end_at"].isoformat(),
        "all_day": r["all_day"],
        "location": r["location"],
        "link": r["link"],
        "attendees": r["attendees"],
        "my_status": r["my_status"],
        "cancelled": r["cancelled"],
        "calendar": r["calendar"],
        "scopes": list(r["scopes"]),
        "prep": r.get("prep"),
        "local": bool(r.get("local")),
    }


def between(conn: Conn, start: datetime, end: datetime) -> list[dict[str, Any]]:
    rows = conn.execute(
        EVENT_SQL + " AND e.start_at < %s AND e.end_at > %s AND NOT e.cancelled"
        " ORDER BY e.all_day DESC, e.start_at",
        (end, start),
    ).fetchall()
    return [to_dict(r) for r in rows]


def today(conn: Conn, now: datetime) -> list[dict[str, Any]]:
    from kb.routines import KYIV

    local = now.astimezone(KYIV)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return between(conn, start, start + timedelta(days=1))


def get(conn: Conn, event_id: int) -> dict[str, Any] | None:
    row = conn.execute(EVENT_SQL + " AND e.id = %s", (event_id,)).fetchone()
    return to_dict(row) if row else None


def headline(r: dict[str, Any]) -> str:
    from kb.routines import KYIV

    others = [a for a in r["attendees"] if a.get("status") != "DECLINED"]
    people = f" — {len(others)} people" if len(others) > 1 else ""
    prep = ", prep ready" if r.get("prep") and people else ""
    return f"{r['start_at'].astimezone(KYIV):%H:%M} {r['title'] or 'Meeting'}{people}{prep}"


def remind_due(conn: Conn, now: datetime) -> int:
    from kb import push

    sent = 0
    for r in conn.execute(
        EVENT_SQL
        + """ AND NOT e.all_day AND NOT e.cancelled AND e.reminded_at IS NULL
          AND c.remind_minutes > 0 AND coalesce(e.my_status, '') <> 'DECLINED'
          AND e.start_at > %s AND e.start_at - make_interval(mins => c.remind_minutes) <= %s
        ORDER BY e.start_at""",
        (now, now),
    ).fetchall():
        conn.execute("UPDATE events SET reminded_at = %s WHERE id = %s", (now, r["id"]))
        sent += push.send(conn, "meetings", headline(dict(r)), f"/meetings/{r['id']}", now)
    return sent


# --- preparation (calendar-meetings spec: meeting preparation; design D20) --------------------

PREP_BEFORE = timedelta(minutes=30)
EARLY_HOUR, EARLY_PREP_HOUR = 10, 7  # meetings before 10:00 are prepared from 07:00 (morning brief)
AGENDA_POINTS = 5

AGENDA_SYSTEM = """You prepare the owner for a meeting. From the facts (earlier conversations, open
promises both ways, the attendees' open tasks, goals) suggest an agenda of at most 5 short points
in the language most used in the facts. Each point must cite the fact it comes from in `ref`,
exactly as written (e.g. "item:12", "loop:3"). Never invent topics that are not in the facts."""

AGENDA_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "agenda": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"text": {"type": "string"}, "ref": {"type": "string"}},
                "required": ["text", "ref"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["agenda"],
    "additionalProperties": False,
}


def prep_due(r: dict[str, Any], now: datetime) -> bool:
    from kb.routines import KYIV

    start = r["start_at"]
    if start <= now:
        return False
    local = start.astimezone(KYIV)
    if local.hour < EARLY_HOUR:
        early = local.replace(hour=EARLY_PREP_HOUR, minute=0, second=0, microsecond=0)
        return now >= early or now >= start - PREP_BEFORE
    return now >= start - PREP_BEFORE


def facts(conn: Conn, r: dict[str, Any], owner: set[str]) -> dict[str, Any]:
    """Who is coming and what is open with them: all from the database, no AI."""
    from kb import loops, people
    from kb.routines import KYIV

    attendees = [a for a in r["attendees"] if a.get("email") and a["email"] not in owner]
    keys = [people.email_key(a["email"]) for a in attendees]
    who = []
    for a, k in zip(attendees, keys, strict=True):
        pid = conn.execute("SELECT person_id FROM identities WHERE key = %s", (k,)).fetchone()
        name = a.get("name") or a["email"]
        if pid:
            p = conn.execute("SELECT display_name FROM people WHERE id = %s", (pid["person_id"],))
            row = p.fetchone()
            name = (row["display_name"] if row else None) or name
        who.append(
            {"email": a["email"], "name": name, "person_id": pid["person_id"] if pid else None}
        )
    convos = (
        [
            {
                "ref": f"item:{c['id']}",
                "title": c["title"],
                "summary": c["summary"],
                "date": c["last_activity_at"].astimezone(KYIV).date().isoformat(),
            }
            for c in conn.execute(
                "SELECT id, title, coalesce(summary, question, '') AS summary, last_activity_at"
                " FROM items WHERE identity_keys && %s AND NOT hidden"
                " AND kind IN ('email_thread', 'tg_conversation', 'clickup_task')"
                " AND NOT coalesce((metadata->>'private')::boolean, false)"
                " ORDER BY last_activity_at DESC NULLS LAST LIMIT 6",
                (keys,),
            ).fetchall()
        ]
        if keys
        else []
    )
    names = [w["name"].lower() for w in who] + [w["email"] for w in who]
    open_loops = []
    for lp in loops.list_loops(conn, r["start_at"], "open"):
        cp = (lp["counterpart"] or "").lower()
        if cp and any(n and (n in cp or cp in n) for n in names):
            open_loops.append(
                {
                    "ref": lp["ref"],
                    "kind": lp["kind"],
                    "title": lp["title"],
                    "counterpart": lp["counterpart"],
                    "due_date": lp["due_date"],
                }
            )
    emails = [w["email"] for w in who]
    tasks = (
        [
            {"ref": f"item:{t['id']}", "title": t["title"], "status": t["status"], "due": t["due"]}
            for t in conn.execute(
                "SELECT id, title, metadata->>'status' AS status, metadata->>'due_date' AS due"
                " FROM items WHERE kind = 'clickup_task' AND NOT hidden"
                " AND coalesce(metadata->>'status_type', '') NOT IN ('closed', 'done')"
                " AND EXISTS (SELECT 1 FROM jsonb_array_elements_text("
                "     coalesce(metadata->'assignee_emails', '[]'::jsonb)) e WHERE e = ANY(%s))"
                " ORDER BY last_activity_at DESC NULLS LAST LIMIT 8",
                (emails,),
            ).fetchall()
        ]
        if emails
        else []
    )
    goals = [
        {"title": g["title"], "scope": g["scope"]}
        for g in conn.execute(
            "SELECT title, scope FROM goals WHERE status = 'confirmed' AND scope = ANY(%s)",
            (list(r["scopes"]),),
        ).fetchall()
    ]
    return {
        "people": who,
        "conversations": convos,
        "loops": open_loops,
        "tasks": tasks,
        "goals": goals,
    }


def _facts_text(r: dict[str, Any], f: dict[str, Any]) -> str:
    lines = [
        f"MEETING: {r['title']} ({r['start_at']:%Y-%m-%d %H:%M} UTC)",
        "ATTENDEES: " + ", ".join(p["name"] for p in f["people"]),
    ]
    lines += [f"[{c['ref']}] {c['date']} {c['title']}: {c['summary']}" for c in f["conversations"]]
    lines += [
        f"[{lp['ref']}] {lp['kind']} {lp['counterpart']}: {lp['title']}"
        + (f" (due {lp['due_date']})" if lp["due_date"] else "")
        for lp in f["loops"]
    ]
    lines += [f"[{t['ref']}] task: {t['title']} ({t['status']})" for t in f["tasks"]]
    lines += [f"GOAL ({g['scope']}): {g['title']}" for g in f["goals"]]
    return "\n".join(lines)


def prepare(
    conn: Conn, config: Any, llm: Any, r: dict[str, Any], owner: set[str], now: datetime
) -> dict[str, Any]:
    from kb import distill, settings_store

    f = facts(conn, r, owner)
    allowed = (
        {c["ref"] for c in f["conversations"]}
        | {lp["ref"] for lp in f["loops"]}
        | {t["ref"] for t in f["tasks"]}
    )
    f["agenda"] = []
    within = distill.month_spend_usd(conn, now.date()) < settings_store.budget_usd(conn, config)
    if llm is not None and allowed and within:
        model = config.llm.briefs_model()
        try:
            data, usage = llm.structured(
                model, AGENDA_SYSTEM, _facts_text(r, f), AGENDA_SCHEMA, "agenda", "low"
            )
            distill.record_usage(conn, "assistant", model, "meeting_prep", usage)
            f["agenda"] = [a for a in data.get("agenda", []) if a.get("ref") in allowed][
                :AGENDA_POINTS
            ]
        except Exception:
            import logging

            logging.getLogger(__name__).exception("agenda for event %s failed", r["id"])
    return f


def prepare_due(conn: Conn, config: Any, llm: Any, now: datetime) -> int:
    """Prepares upcoming meetings with other attendees, once each (re-prepared if they move)."""
    from kb import loops

    owner = loops.owner_emails(conn, config)
    done = 0
    for r in conn.execute(
        EVENT_SQL
        + """ AND NOT e.all_day AND NOT e.cancelled AND coalesce(e.my_status, '') <> 'DECLINED'
          AND e.prepared_at IS NULL AND e.start_at > %s AND e.start_at < %s
          AND jsonb_array_length(e.attendees) > 1
        ORDER BY e.start_at LIMIT 5""",
        (now, now + timedelta(hours=24)),
    ).fetchall():
        row = dict(r)
        if not prep_due(row, now):
            continue
        prep = prepare(conn, config, llm, row, owner, now)
        conn.execute(
            "UPDATE events SET prep = %s, prepared_at = %s WHERE id = %s",
            (Jsonb(prep), now, r["id"]),
        )
        done += 1
    return done


def early_meetings(conn: Conn, now: datetime) -> list[dict[str, Any]]:
    """Today's meetings before 10:00 (Kyiv): the morning brief links their prep."""
    from kb.routines import KYIV

    local = now.astimezone(KYIV)
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return [
        m
        for m in between(conn, start, local.replace(hour=EARLY_HOUR, minute=0, second=0))
        if not m["all_day"] and m["my_status"] != "DECLINED"
    ]


# --- meetings around now (for devices) and meetings outside the calendar ------------------------


class MeetingError(ValueError):
    pass


def around(conn: Conn, now: datetime, hours: int = 12) -> list[dict[str, Any]]:
    """Minimal fields for a device's meeting picker: the one in progress first."""
    rows = conn.execute(
        EVENT_SQL + " AND NOT e.all_day AND NOT e.cancelled AND e.start_at < %s AND e.end_at > %s"
        " ORDER BY e.start_at",
        (now + timedelta(hours=hours), now - timedelta(hours=hours)),
    ).fetchall()
    out = [
        {
            "id": r["id"],
            "title": r["title"] or "Meeting",
            "start": r["start_at"].isoformat(),
            "end": r["end_at"].isoformat(),
            "in_progress": r["start_at"] <= now < r["end_at"],
        }
        for r in rows
    ]
    return sorted(out, key=lambda m: (not m["in_progress"], abs(_dist(m, now))))


def _dist(m: dict[str, Any], now: datetime) -> float:
    return (datetime.fromisoformat(m["start"]) - now).total_seconds()


def local_calendar(conn: Conn) -> int:
    row = conn.execute(
        "SELECT c.id FROM calendars c JOIN connector_accounts a ON a.id = c.account_id"
        " WHERE a.kind = 'calendar' AND a.settings->>'type' = 'local' LIMIT 1"
    ).fetchone()
    if row is not None:
        return int(row["id"])
    account = conn.execute(  # created by migration 0044; recreated if it was removed
        "INSERT INTO connector_accounts (kind, label, settings) VALUES ('calendar',"
        " 'Second brain', '{\"type\": \"local\"}'::jsonb) RETURNING id"
    ).fetchone()
    assert account is not None
    cal = conn.execute(
        "INSERT INTO calendars (account_id, href, name, sync, scopes, remind_minutes)"
        " VALUES (%s, 'local', 'Second brain', true, '{unsorted}', 0) RETURNING id",
        (account["id"],),
    ).fetchone()
    assert cal is not None
    return int(cal["id"])


def participants(conn: Conn, entries: list[str]) -> list[dict[str, Any]]:
    """Names or emails → attendees, linked to People when unambiguous."""
    from kb import people

    out = []
    for raw in entries:
        entry = raw.strip()
        if not entry:
            continue
        person_id, email, name = None, "", entry
        if "@" in entry:
            email = entry.lower()
            row = conn.execute(
                "SELECT person_id FROM identities WHERE key = %s", (people.email_key(email),)
            ).fetchone()
            person_id = row["person_id"] if row else None
        else:
            found = [
                p
                for p in people.find(conn, entry, 5)
                if (p["display_name"] or "").lower() == entry.lower()
                or (p["display_name"] or "").lower().split()[:1] == [entry.lower()]
            ]
            if len(found) == 1:
                person_id, name = found[0]["id"], found[0]["display_name"]
                key = conn.execute(
                    "SELECT key FROM identities WHERE person_id = %s AND key LIKE 'email:%%'"
                    " LIMIT 1",
                    (person_id,),
                ).fetchone()
                email = key["key"].removeprefix("email:") if key else ""
        if person_id is not None and name == entry and "@" in entry:
            p = conn.execute(
                "SELECT display_name FROM people WHERE id = %s", (person_id,)
            ).fetchone()
            name = (p["display_name"] if p else None) or entry
        out.append({"email": email, "name": name, "status": "ACCEPTED", "person_id": person_id})
    return out


def create_local(
    conn: Conn,
    title: str,
    scope: str | None,
    start: datetime,
    end: datetime,
    people_: list[str] | None = None,
) -> int:
    """A meeting that is not in any connected calendar (spontaneous calls)."""
    import uuid

    from kb import scopes

    if not title.strip():
        raise MeetingError("a meeting needs a title")
    if scope and scope not in (*scopes.known(conn), "unsorted"):
        raise MeetingError(f"unknown project {scope!r}")
    if end < start:
        raise MeetingError("the meeting ends before it starts")
    row = conn.execute(
        "INSERT INTO events (calendar_id, uid, start_at, end_at, title, attendees, my_status,"
        " scopes) VALUES (%s, %s, %s, %s, %s, %s, 'ACCEPTED', %s) RETURNING id",
        (
            local_calendar(conn),
            f"local-{uuid.uuid4()}",
            start,
            end,
            title.strip()[:200],
            Jsonb(participants(conn, people_ or [])),
            [scope] if scope else None,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def update_local(
    conn: Conn,
    event_id: int,
    title: str | None = None,
    scope: str | None = None,
    people_: list[str] | None = None,
) -> None:
    from kb import scopes

    row = conn.execute(
        "SELECT c.href FROM events e JOIN calendars c ON c.id = e.calendar_id WHERE e.id = %s",
        (event_id,),
    ).fetchone()
    if row is None:
        raise MeetingError(f"no meeting {event_id}")
    if row["href"] != "local":
        raise MeetingError("meetings from Google or iCloud are read-only")
    if title is not None and not title.strip():
        raise MeetingError("a meeting needs a title")
    if scope is not None and scope not in (*scopes.known(conn), "unsorted"):
        raise MeetingError(f"unknown project {scope!r}")
    conn.execute(
        "UPDATE events SET title = coalesce(%s, title), scopes = coalesce(%s, scopes),"
        " attendees = coalesce(%s, attendees), updated_at = now() WHERE id = %s",
        (
            title.strip()[:200] if title is not None else None,
            [scope] if scope is not None else None,
            Jsonb(participants(conn, people_)) if people_ is not None else None,
            event_id,
        ),
    )
