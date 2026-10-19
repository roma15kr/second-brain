"""Meetings from the owner's calendars (calendar-meetings spec): listing, reminders.

A reminder is pushed `remind_minutes` before each timed meeting the owner has not declined (all-day
and cancelled events never); quiet hours apply, and an event is reminded at most once.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from kb.db import Conn

EVENT_SQL = """
    SELECT e.*, c.name AS calendar, c.scopes, c.remind_minutes FROM events e
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
    return f"{r['start_at'].astimezone(KYIV):%H:%M} {r['title'] or 'Meeting'}{people}"


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
