"""Calendars and meetings (calendar-meetings spec): connect read-only, mark, list meetings."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from kb import meetings, people, scopes
from kb.api.deps import get_conn
from kb.connectors import calendar
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


def _transport(request: Request) -> Any:
    return getattr(request.app.state, "calendar_transport", None)  # replaced in tests


@router.post("/api/connectors/calendars/ical")
def connect_ical(
    request: Request,
    conn: Db,
    url: Annotated[str, Body(embed=True)],
    name: Annotated[str, Body(embed=True)] = "",
) -> dict[str, int]:
    try:
        return {"account_id": calendar.connect_ical(conn, url, name, _transport(request))}
    except (calendar.CalendarError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:  # unreachable host, TLS errors…
        raise HTTPException(400, f"could not read the calendar: {e}") from e


@router.post("/api/connectors/calendars/caldav")
def connect_caldav(
    request: Request,
    conn: Db,
    username: Annotated[str, Body(embed=True)],
    password: Annotated[str, Body(embed=True)],
    base: Annotated[str, Body(embed=True)] = calendar.ICLOUD,
) -> dict[str, int]:
    if not base.startswith("https://"):
        raise HTTPException(400, "the CalDAV server must use https://")
    try:
        return {
            "account_id": calendar.connect_caldav(
                conn, username.strip(), password.strip(), base, _transport(request)
            )
        }
    except calendar.CalendarError as e:
        raise HTTPException(400, str(e)) from e
    except Exception as e:
        raise HTTPException(400, f"could not reach the CalDAV server: {e}") from e


@router.get("/api/connectors/calendars")
def overview(conn: Db) -> dict[str, Any]:
    accounts = conn.execute(
        "SELECT id, label, settings->>'type' AS type, state FROM connector_accounts"
        " WHERE kind = 'calendar' ORDER BY id"
    ).fetchall()
    cals = conn.execute(
        "SELECT c.*, (SELECT count(*) FROM events e WHERE e.calendar_id = c.id) AS events"
        " FROM calendars c ORDER BY c.account_id, c.name"
    ).fetchall()
    return {
        "accounts": [dict(a) for a in accounts],
        "calendars": [
            {
                "id": c["id"],
                "account_id": c["account_id"],
                "name": c["name"],
                "sync": c["sync"],
                "scopes": list(c["scopes"]),
                "remind_minutes": c["remind_minutes"],
                "events": c["events"],
                "synced_at": c["synced_at"].isoformat() if c["synced_at"] else None,
                "error": c["error"],
            }
            for c in cals
        ],
    }


@router.post("/api/connectors/calendars/{cal_id}")
def mark(
    conn: Db,
    cal_id: int,
    sync: Annotated[bool | None, Body(embed=True)] = None,
    scopes_: Annotated[list[str] | None, Body(embed=True, alias="scopes")] = None,
    remind_minutes: Annotated[int | None, Body(embed=True)] = None,
) -> dict[str, bool]:
    row = conn.execute("SELECT * FROM calendars WHERE id = %s", (cal_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no calendar {cal_id}")
    if scopes_ is not None:
        try:
            scopes.validate_scopes(scopes_, scopes.known(conn))
        except scopes.ReviewError as e:
            raise HTTPException(400, str(e)) from e
    if (sync or (sync is None and row["sync"])) and not (scopes_ or row["scopes"]):
        raise HTTPException(400, "mark the calendar (personal or a project) before syncing it")
    if remind_minutes is not None and not 0 <= remind_minutes <= 240:
        raise HTTPException(400, "reminders can be 0 to 240 minutes before")
    conn.execute(
        "UPDATE calendars SET sync = coalesce(%s, sync), scopes = coalesce(%s, scopes),"
        " remind_minutes = coalesce(%s, remind_minutes), synced_at = NULL WHERE id = %s",
        (sync, scopes_, remind_minutes, cal_id),
    )
    if sync is False:
        conn.execute("DELETE FROM events WHERE calendar_id = %s", (cal_id,))
    return {"ok": True}


@router.delete("/api/connectors/calendars/accounts/{account_id}")
def disconnect(conn: Db, account_id: int) -> dict[str, bool]:
    if not conn.execute(
        "DELETE FROM connector_accounts WHERE id = %s AND kind = 'calendar' RETURNING id",
        (account_id,),
    ).fetchone():
        raise HTTPException(404, f"no calendar account {account_id}")
    return {"ok": True}


@router.get("/api/meetings")
def listing(conn: Db, days: int = 7) -> dict[str, Any]:
    from kb.routines import KYIV

    start = datetime.now(UTC).astimezone(KYIV).replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "meetings": meetings.between(conn, start, start + timedelta(days=max(1, min(days, 60))))
    }


@router.get("/api/meetings/{event_id}")
def meeting(conn: Db, event_id: int) -> dict[str, Any]:
    m = meetings.get(conn, event_id)
    if m is None:
        raise HTTPException(404, f"no meeting {event_id}")
    for a in m["attendees"]:  # link attendees to the people directory
        pid = conn.execute(
            "SELECT person_id FROM identities WHERE key = %s", (people.email_key(a["email"]),)
        ).fetchone()
        a["person_id"] = pid["person_id"] if pid else None
    return m
