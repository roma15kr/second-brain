"""Week page: Friday review and Monday plan of a week; accept or edit the plan."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException

from kb import loops
from kb.api.deps import get_conn
from kb.db import Conn
from kb.routines import briefs, weekly

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


@router.get("/api/week")
def week(conn: Db, start: date | None = None) -> dict[str, Any]:
    monday = weekly.week_start(start or loops.kyiv_today(datetime.now(UTC)))
    review = conn.execute(
        "SELECT * FROM briefs WHERE routine = 'weekly_review'"
        " AND (created_at AT TIME ZONE 'Europe/Kyiv')::date BETWEEN %s AND %s"
        " ORDER BY id DESC LIMIT 1",
        (monday, monday + timedelta(days=6)),
    ).fetchone()
    plan = conn.execute(
        "SELECT p.*, b.id AS bid FROM weekly_plans p JOIN briefs b ON b.id = p.brief_id"
        " WHERE p.week_start = %s ORDER BY p.brief_id DESC LIMIT 1",
        (monday,),
    ).fetchone()
    plan_brief = None
    if plan:
        row = conn.execute("SELECT * FROM briefs WHERE id = %s", (plan["bid"],)).fetchone()
        assert row is not None  # joined above
        plan_brief = {
            "brief": briefs.to_dict(row),
            "proposed": plan["proposed"],
            "accepted": plan["accepted"],
            "accepted_at": plan["accepted_at"].isoformat() if plan["accepted_at"] else None,
        }
    weeks = [
        r["w"].isoformat()
        for r in conn.execute(
            "SELECT DISTINCT date_trunc('week', created_at AT TIME ZONE 'Europe/Kyiv')::date AS w"
            " FROM briefs WHERE routine IN ('weekly_review', 'weekly_plan') ORDER BY w DESC"
            " LIMIT 52"
        )
    ]
    return {
        "week_start": monday.isoformat(),
        "review": briefs.to_dict(review) if review else None,
        "plan": plan_brief,
        "weeks": weeks,
    }


@router.post("/api/week/plan/{brief_id}/accept")
def accept(
    conn: Db,
    brief_id: int,
    priorities: Annotated[list[dict[str, Any]] | None, Body(embed=True)] = None,
) -> dict[str, bool]:
    try:
        weekly.accept_plan(conn, brief_id, datetime.now(UTC), priorities)
    except ValueError as e:
        raise HTTPException(404, str(e)) from e
    return {"ok": True}
