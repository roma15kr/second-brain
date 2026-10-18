"""Open loops list and actions (open-loops spec; web-dashboard spec: Loops page)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException

from kb import loops
from kb.api.deps import get_conn
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]
Status = Literal["open", "done", "snoozed", "dismissed"]
Kind = Literal["needs_reply", "i_owe", "owed_to_me", "manual"]


@router.get("/api/loops")
def list_loops(
    conn: Db,
    status: Status = "open",
    kind: Kind | None = None,
    scope: str | None = None,
    person: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(UTC)
    rows = loops.list_loops(conn, now, status, kind, scope, person)
    counts = conn.execute(
        "SELECT kind, count(*) AS n FROM loops WHERE status = 'open' GROUP BY kind"
    ).fetchall()
    return {"loops": rows, "open_counts": {r["kind"]: r["n"] for r in counts}}


@router.post("/api/loops/{loop_id}/act")
def act(
    conn: Db,
    loop_id: int,
    action: Annotated[Literal["done", "dismiss", "snooze", "due", "reopen"], Body(embed=True)],
    until: Annotated[date | None, Body(embed=True)] = None,
    due: Annotated[date | None, Body(embed=True)] = None,
) -> dict[str, bool]:
    try:
        loops.act(conn, loop_id, action, datetime.now(UTC), until=until, due=due)
    except loops.LoopError as e:
        raise HTTPException(404 if str(e).startswith("no loop") else 400, str(e)) from e
    return {"ok": True}


@router.post("/api/loops")
def add(
    conn: Db,
    title: Annotated[str, Body(embed=True)],
    due: Annotated[date | None, Body(embed=True)] = None,
    counterpart: Annotated[str, Body(embed=True)] = "",
    scope: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, int]:
    try:
        loop_id = loops.add_manual(
            conn, title, datetime.now(UTC), due, counterpart, [scope] if scope else []
        )
    except loops.LoopError as e:
        raise HTTPException(400, str(e)) from e
    return {"id": loop_id}
