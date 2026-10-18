"""Inbox: the latest mail revision pass and its actions (web-dashboard spec: Inbox page)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from kb import loops, scopes
from kb.api.deps import get_conn
from kb.db import Conn
from kb.routines import triage

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


def _now() -> datetime:
    return datetime.now(UTC)


@router.get("/api/inbox")
def inbox(conn: Db) -> dict[str, Any]:
    latest = conn.execute(
        "SELECT id, headline, created_at FROM briefs WHERE routine = 'revision'"
        " ORDER BY id DESC LIMIT 1"
    ).fetchone()
    groups: dict[str, list[dict[str, Any]]] = {c: [] for c in triage.CLASSES}
    if latest is None:
        return {"pass": None, "groups": groups}
    rows = conn.execute(
        """
        SELECT t.item_id, t.class, t.action, t.reason, t.sender, i.title, i.scopes, i.locator,
               coalesce(i.summary, i.question, '') AS summary, i.last_activity_at
        FROM triage t JOIN items i ON i.id = t.item_id
        WHERE t.brief_id = %s AND t.done_at IS NULL
          AND (t.snoozed_until IS NULL OR t.snoozed_until <= %s)
        ORDER BY i.last_activity_at DESC
        """,
        (latest["id"], _now()),
    ).fetchall()
    for r in rows:
        groups[r["class"]].append(
            {
                "item_id": r["item_id"],
                "title": r["title"] or "(no subject)",
                "summary": r["summary"],
                "action": r["action"],
                "reason": r["reason"],
                "sender": r["sender"],
                "scopes": list(r["scopes"]),
                "link": r["locator"] if str(r["locator"] or "").startswith("https://") else None,
                "last_activity_at": r["last_activity_at"].isoformat(),
            }
        )
    return {
        "pass": {
            "id": latest["id"],
            "headline": latest["headline"],
            "created_at": latest["created_at"].isoformat(),
        },
        "groups": groups,
    }


def _triaged(conn: Conn, item_id: int) -> None:
    if not conn.execute("SELECT 1 FROM triage WHERE item_id = %s", (item_id,)).fetchone():
        raise HTTPException(404, f"item {item_id} is not in the inbox")


@router.post("/api/inbox/{item_id}/done")
def done(conn: Db, item_id: int) -> dict[str, bool]:
    _triaged(conn, item_id)
    conn.execute(
        "UPDATE triage SET done_at = %s WHERE item_id = %s AND done_at IS NULL", (_now(), item_id)
    )
    loops.close_for_item(conn, item_id, _now())
    return {"ok": True}


@router.post("/api/inbox/{item_id}/snooze")
def snooze(conn: Db, item_id: int, until: Annotated[datetime, Body(embed=True)]) -> dict[str, bool]:
    _triaged(conn, item_id)
    if until.tzinfo is None or until <= _now():
        raise HTTPException(400, "until must be a future time with a time zone")
    conn.execute("UPDATE triage SET snoozed_until = %s WHERE item_id = %s", (until, item_id))
    return {"ok": True}


@router.post("/api/inbox/{item_id}/scope")
def change_scope(
    request: Request,
    conn: Db,
    item_id: int,
    scope: Annotated[str, Body(embed=True)],
    apply_to: Annotated[Literal["item", "sender"], Body(embed=True)] = "item",
) -> dict[str, str]:
    try:
        message = scopes.assign(
            conn,
            request.app.state.config,
            item_id,
            [scope],
            None if apply_to == "item" else "sender",
        )
    except (scopes.ReviewError, ValueError) as e:
        raise HTTPException(400, str(e)) from e
    return {"result": message}


@router.post("/api/senders/pref")
def sender_pref(
    conn: Db,
    address: Annotated[str, Body(embed=True)],
    pref: Annotated[Literal["noise", "important"] | None, Body(embed=True)] = None,
) -> dict[str, bool]:
    """Mark a sender as noise or important; null clears the preference."""
    triage.set_sender_pref(conn, address, pref)
    return {"ok": True}
