"""Focus protection, attention audit and decision log (assistant-actions spec; design D21).

All from data: free blocks = working hours minus meetings (>= 90 min); meeting load = meeting
minutes / working minutes; attention = activity per area this week vs confirmed goals;
neglected goal = no related activity for 14 days; decisions = conversation outcomes and meeting
decisions of the week.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from kb import settings_store
from kb.db import Conn

FOCUS_MINUTES = 90
OVERLOAD = 0.5  # meetings over half of the working hours
NEGLECT_DAYS = 14


@dataclass
class Day:
    day: date
    work_minutes: int
    meeting_minutes: int
    free: list[tuple[datetime, datetime]]
    meetings: list[dict[str, Any]]

    @property
    def load(self) -> float:
        return self.meeting_minutes / self.work_minutes if self.work_minutes else 0.0

    @property
    def overloaded(self) -> bool:
        return self.load > OVERLOAD


def day_load(conn: Conn, day: date) -> Day:
    from kb import meetings
    from kb.routines import KYIV

    wh = settings_store.load(conn).working_hours
    start = datetime.combine(day, wh.start, tzinfo=KYIV)
    end = datetime.combine(day, wh.end, tzinfo=KYIV)
    ms = [
        m
        for m in meetings.between(conn, start, end)
        if not m["all_day"] and m["my_status"] != "DECLINED"
    ]
    busy = []
    for m in ms:
        s = max(datetime.fromisoformat(m["start"]), start)
        e = min(datetime.fromisoformat(m["end"]), end)
        if e > s:
            busy.append((s, e))
    busy.sort()
    merged: list[tuple[datetime, datetime]] = []
    for s, e in busy:
        if merged and s <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    free, cursor = [], start
    for s, e in [*merged, (end, end)]:
        if (s - cursor) >= timedelta(minutes=FOCUS_MINUTES):
            free.append((cursor, s))
        cursor = max(cursor, e)
    meeting = sum(int((e - s).total_seconds() // 60) for s, e in merged)
    return Day(day, int((end - start).total_seconds() // 60), meeting, free, ms)


def _hm(t: datetime) -> str:
    from kb.routines import KYIV

    return t.astimezone(KYIV).strftime("%H:%M")


def _hours(minutes: int) -> str:
    h, m = divmod(minutes, 60)
    return f"{h} h" + (f" {m} min" if m else "")


def focus_section(conn: Conn, now: datetime, priorities: list[dict[str, Any]]) -> str | None:
    """Morning brief: today's free blocks with a priority each, and a warning on a heavy day."""
    from kb import loops

    if not conn.execute("SELECT 1 FROM calendars WHERE sync LIMIT 1").fetchone():
        return None  # without a calendar every day would look free
    d = day_load(conn, loops.kyiv_today(now))
    lines = []
    for n, (s, e) in enumerate(d.free):
        what = f" → {priorities[n]['title']}" if n < len(priorities) else ""
        span = _hours(int((e - s).total_seconds() // 60))
        lines.append(f"{_hm(s)}-{_hm(e)} ({span}){what}")
    if d.overloaded:
        lines.append(
            f"⚠ Meetings fill {_hours(d.meeting_minutes)} of {_hours(d.work_minutes)} working"
            " hours today."
        )
    if not lines and d.meetings:
        lines.append("No free block of 90 minutes today.")
    return "\n".join(lines) or None


def tomorrow_warning(conn: Conn, now: datetime) -> str | None:
    """Evening wrap: tomorrow is meeting-heavy → which meeting could be shortened or moved."""
    from kb import loops

    d = day_load(conn, loops.kyiv_today(now) + timedelta(days=1))
    if not d.overloaded:
        return None

    def minutes(m: dict[str, Any]) -> int:
        return int(
            (datetime.fromisoformat(m["end"]) - datetime.fromisoformat(m["start"])).total_seconds()
            // 60
        )

    longest = max(d.meetings, key=minutes)
    return (
        f"Tomorrow meetings fill {_hours(d.meeting_minutes)} of {_hours(d.work_minutes)} working"
        f" hours. Consider shortening or moving “{longest['title']}”"
        f" ({_hm(datetime.fromisoformat(longest['start']))}, {minutes(longest)} min)."
    )


# --- decline / defer ------------------------------------------------------------------------

DECLINE_SYSTEM = """Write a short, polite message (2-3 sentences) from the owner declining or
proposing to move a meeting invitation because the day is full. Use the language of the title.
No excuses beyond "my schedule that day is full"; offer to find another time. Body only."""
DECLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"body": {"type": "string"}},
    "required": ["body"],
    "additionalProperties": False,
}


def decline_suggestions(conn: Conn, config: Any, llm: Any, now: datetime) -> int:
    """Unanswered invitations on overloaded days that serve no confirmed goal → a polite draft to
    copy (calendars are read-only; the owner answers in their calendar app)."""
    from kb import distill, loops
    from kb.assistant import proactive, suggestions

    if not proactive.allowed(conn, "decline", now):
        return 0
    today = loops.kyiv_today(now)
    goal_scopes = {
        r["scope"]
        for r in conn.execute("SELECT DISTINCT scope FROM goals WHERE status = 'confirmed'")
    }
    done = 0
    for offset in range(1, 8):
        d = day_load(conn, today + timedelta(days=offset))
        if not d.overloaded:
            continue
        for m in d.meetings:
            if m["my_status"] not in ("NEEDS-ACTION", "TENTATIVE"):
                continue
            if set(m["scopes"]) & goal_scopes:
                continue
            if conn.execute(
                "SELECT 1 FROM suggestions WHERE kind = 'decline'"
                " AND (payload->>'event_id')::bigint = %s",
                (m["id"],),
            ).fetchone():
                continue
            body = (
                f"Thank you for the invitation to “{m['title']}”. My schedule that day is full;"
                " could we find another time?"
            )
            if llm is not None:
                try:
                    model = config.llm.model()
                    data, usage = llm.structured(
                        model,
                        DECLINE_SYSTEM,
                        f"MEETING: {m['title']}",
                        DECLINE_SCHEMA,
                        "decline",
                        "low",
                    )
                    distill.record_usage(conn, "assistant", model, "decline", usage)
                    body = str(data.get("body") or body).strip()
                except Exception:
                    pass
            organizer = next(
                (a["email"] for a in m["attendees"] if a.get("status") == "ACCEPTED"), ""
            )
            suggestions.propose(
                conn,
                "decline",
                {"event_id": m["id"], "title": m["title"], "to": organizer, "body": body},
                reason=f"{d.day:%a %d %b} is {round(d.load * 100)}% meetings and"
                " this serves no confirmed goal",
                scopes=m["scopes"],
            )
            done += 1
            return done  # at most one a cycle
    return done


# --- weekly: attention, neglected goals, decisions ----------------------------------------------


def attention(conn: Conn, start: datetime, end: datetime) -> list[str]:
    """Per area this week: conversations, meeting hours and ClickUp tasks, with its goals."""
    rows = conn.execute(
        """
        SELECT s AS scope,
               count(*) FILTER (WHERE kind IN ('email_thread', 'tg_conversation')) AS conversations,
               count(*) FILTER (WHERE kind = 'clickup_task') AS tasks
        FROM items, unnest(scopes) s
        WHERE NOT hidden AND last_activity_at >= %s AND last_activity_at < %s
        GROUP BY s ORDER BY count(*) DESC
        """,
        (start, end),
    ).fetchall()
    meeting = {
        r["scope"]: int(r["m"])
        for r in conn.execute(
            "SELECT s AS scope, sum(extract(epoch FROM e.end_at - e.start_at) / 60) AS m"
            " FROM events e JOIN calendars c ON c.id = e.calendar_id,"
            " unnest(coalesce(e.scopes, c.scopes)) s"
            " WHERE c.sync AND NOT e.all_day AND NOT e.cancelled"
            " AND coalesce(e.my_status, '') <> 'DECLINED' AND e.start_at >= %s AND e.start_at < %s"
            " GROUP BY s",
            (start, end),
        ).fetchall()
    }
    goals: dict[str, int] = {}
    for g in conn.execute("SELECT scope FROM goals WHERE status = 'confirmed'").fetchall():
        goals[g["scope"]] = goals.get(g["scope"], 0) + 1
    scopes = list(dict.fromkeys([r["scope"] for r in rows] + list(meeting) + list(goals)))
    by = {r["scope"]: r for r in rows}
    lines = []
    for s in scopes:
        r = by.get(s)
        parts = [
            f"{r['conversations'] if r else 0} conversations",
            f"{_hours(meeting.get(s, 0))} meetings",
            f"{r['tasks'] if r else 0} tasks",
        ]
        n_goals = goals.get(s, 0)
        tail = f" · {n_goals} goals" if n_goals else " · no goals"
        lines.append(f"{s}: " + ", ".join(parts) + tail)
    return lines


def neglected_goals(conn: Conn, now: datetime) -> list[dict[str, Any]]:
    """Confirmed goals with no related activity (meaning match in the goal's area) for 14 days."""
    from kb.assistant.priority import GOAL_SIMILARITY

    since = now - timedelta(days=NEGLECT_DAYS)
    out = []
    for g in conn.execute(
        "SELECT id, title, scope, embedding IS NOT NULL AS has_vec FROM goals"
        " WHERE status = 'confirmed' ORDER BY id"
    ).fetchall():
        if g["has_vec"]:
            row = conn.execute(
                "SELECT 1 FROM items i, goals g WHERE g.id = %s AND i.embedding IS NOT NULL"
                " AND NOT i.hidden AND g.scope = ANY(i.scopes) AND i.last_activity_at >= %s"
                " AND 1 - (i.embedding <=> g.embedding) >= %s LIMIT 1",
                (g["id"], since, GOAL_SIMILARITY),
            ).fetchone()
        else:  # not embedded yet: any title word of 5+ letters in the area's items
            words = [w for w in g["title"].lower().split() if len(w) >= 5]
            row = (
                conn.execute(
                    "SELECT 1 FROM items WHERE %s = ANY(scopes) AND NOT hidden"
                    " AND last_activity_at >= %s AND lower(coalesce(title, '') || ' ' ||"
                    " coalesce(summary, '')) ~ %s LIMIT 1",
                    (g["scope"], since, "|".join(map(_re_escape, words))),
                ).fetchone()
                if words
                else None
            )
        if row is None:
            out.append(
                {
                    "goal_id": g["id"],
                    "title": g["title"],
                    "scope": g["scope"],
                    "first_step": f"Block 90 minutes this week for “{g['title']}” and write down"
                    " the next concrete action.",
                }
            )
    return out


def _re_escape(word: str) -> str:
    import re

    return re.escape(word)


def decisions(conn: Conn, start: datetime, end: datetime) -> dict[str, list[dict[str, Any]]]:
    """The week's decisions per area: conversation outcomes and meeting decisions, sourced."""
    out: dict[str, list[dict[str, Any]]] = {}
    for r in conn.execute(
        "SELECT id, title, outcome, scopes, participants, last_activity_at, locator FROM items"
        " WHERE NOT hidden AND outcome IS NOT NULL AND outcome <> ''"
        " AND kind IN ('email_thread', 'tg_conversation', 'clickup_task', 'clickup_chat')"
        " AND last_activity_at >= %s AND last_activity_at < %s ORDER BY last_activity_at",
        (start, end),
    ).fetchall():
        for s in r["scopes"] or ["unsorted"]:
            out.setdefault(s, []).append(
                _decision(
                    r["id"],
                    r["outcome"],
                    r["title"],
                    r["participants"],
                    r["last_activity_at"],
                    r["locator"],
                    list(r["scopes"]),
                )
            )
    for r in conn.execute(
        "SELECT r.item_id, r.title, r.result, r.scopes, r.started_at FROM recordings r"
        " WHERE r.result IS NOT NULL AND r.started_at >= %s AND r.started_at < %s",
        (start, end),
    ).fetchall():
        for d in (r["result"] or {}).get("decisions", []):
            for s in r["scopes"] or ["unsorted"]:
                out.setdefault(s, []).append(
                    _decision(
                        r["item_id"], d, r["title"], [], r["started_at"], None, list(r["scopes"])
                    )
                )
    return out


def _decision(
    item_id: int | None,
    text: str,
    title: str,
    people: list[str],
    when: datetime,
    locator: str | None,
    scopes: list[str],
) -> dict[str, Any]:
    return {
        "ref": f"item:{item_id}",
        "id": item_id,
        "kind": "decision",
        "title": text,
        "summary": f"{title}" + (f" · {', '.join(people[:4])}" if people else ""),
        "outcome": None,
        "link": locator if str(locator or "").startswith("https://") else f"/c/{item_id}",
        "last_activity_at": when.isoformat(),
        "scopes": scopes,
        "participants": people,
    }
