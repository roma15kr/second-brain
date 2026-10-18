"""Goals to confirm from core documents (personal-base spec)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Body, Depends, HTTPException

from kb import goals, scopes
from kb.api.deps import get_conn
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


@router.get("/api/goals")
def listing(conn: Db) -> dict[str, Any]:
    return {"goals": goals.listing(conn)}


@router.post("/api/goals/{goal_id}")
def act(
    conn: Db,
    goal_id: int,
    action: Annotated[Literal["confirm", "remove", "edit"], Body(embed=True)],
    title: Annotated[str | None, Body(embed=True)] = None,
    measure: Annotated[str | None, Body(embed=True)] = None,
    deadline: Annotated[date | None, Body(embed=True)] = None,
    scope: Annotated[str | None, Body(embed=True)] = None,
) -> dict[str, bool]:
    if scope is not None and scope not in scopes.known(conn):
        raise HTTPException(400, f"unknown scope {scope!r}")
    try:
        goals.act(conn, goal_id, action, datetime.now(UTC), title, measure, deadline, scope)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True}
