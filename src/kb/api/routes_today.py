"""Today page data (web-dashboard spec: Today page)."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from kb.api.deps import get_conn
from kb.db import Conn
from kb.routines import briefs

router = APIRouter()


@router.get("/api/today")
def today(conn: Annotated[Conn, Depends(get_conn)]) -> dict[str, Any]:
    from datetime import UTC, datetime

    from kb import meetings

    return {
        "brief": briefs.latest(conn, ["morning", "evening"]),
        "meetings": meetings.today(conn, datetime.now(UTC)),
    }
