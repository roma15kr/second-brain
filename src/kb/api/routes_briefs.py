"""Briefs list and brief pages (web-dashboard spec: Briefs and Week pages)."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from kb import events
from kb.api.deps import get_conn
from kb.db import Conn
from kb.routines import ROUTINES, briefs

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]
PAGE = 30


@router.get("/api/briefs")
def list_briefs(
    conn: Db,
    routine: Annotated[list[str] | None, Query()] = None,
    before: int | None = None,
) -> dict[str, Any]:
    """Newest first, PAGE at a time; `before` = the last id of the previous page."""
    wanted = [r for r in (routine or ROUTINES) if r in ROUTINES]
    rows = conn.execute(
        "SELECT id, routine, headline, mode, created_at FROM briefs"
        " WHERE routine = ANY(%s) AND (%s::bigint IS NULL OR id < %s)"
        " ORDER BY id DESC LIMIT %s",
        (wanted, before, before, PAGE + 1),
    ).fetchall()
    page = rows[:PAGE]
    state = events.brief_state(conn, [r["id"] for r in page])
    return {
        "briefs": [
            {
                "id": r["id"],
                "routine": r["routine"],
                "title": briefs.TITLES.get(r["routine"], r["routine"]),
                "headline": r["headline"],
                "mode": r["mode"],
                "created_at": r["created_at"].isoformat(),
                **state[r["id"]],
            }
            for r in page
        ],
        "next_before": page[-1]["id"] if len(rows) > PAGE else None,
    }


@router.get("/api/briefs/{brief_id}")
def get_brief(conn: Db, brief_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM briefs WHERE id = %s", (brief_id,)).fetchone()
    if row is None:
        raise HTTPException(404, f"no brief {brief_id}")
    return {**briefs.to_dict(row), **events.brief_state(conn, [brief_id])[brief_id]}


@router.post("/api/briefs/{brief_id}/opened")
def opened(
    conn: Db, brief_id: int, via: Annotated[Literal["app", "push"], Body(embed=True)] = "app"
) -> dict[str, bool]:
    events.record(conn, "brief_opened", f"brief:{brief_id}", {"via": via})
    return {"ok": True}


@router.post("/api/briefs/{brief_id}/rating")
def rate(conn: Db, brief_id: int, useful: Annotated[bool, Body(embed=True)]) -> dict[str, bool]:
    events.record(conn, "brief_rating", f"brief:{brief_id}", {"useful": useful})
    return {"ok": True}
