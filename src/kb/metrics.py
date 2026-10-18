"""The web OS success metric (proposal): over the last 28 days, the share of scheduled briefs
the owner opened or rated (target ≥ 80%), and the share of detected open loops that were
resolved — done or dismissed — rather than left open (target ≥ 70%)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from kb.db import Conn

WINDOW_DAYS = 28
BRIEFS_TARGET = 0.8
LOOPS_TARGET = 0.7


def usefulness(conn: Conn, now: datetime, days: int = WINDOW_DAYS) -> dict[str, Any]:
    since = now - timedelta(days=days)
    briefs = conn.execute(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE EXISTS (
                   SELECT 1 FROM app_events e
                   WHERE e.ref = 'brief:' || b.id AND e.kind IN ('brief_opened', 'brief_rating')
               )) AS used
        FROM briefs b
        WHERE b.created_at >= %s AND b.created_at <= %s AND b.push
        """,
        (since, now),
    ).fetchone()
    loops = conn.execute(
        """
        SELECT count(*) AS total,
               count(*) FILTER (WHERE status IN ('done', 'dismissed')) AS resolved
        FROM loops WHERE kind <> 'manual' AND created_at >= %s AND created_at <= %s
        """,
        (since, now),
    ).fetchone()

    def share(part: int, whole: int) -> float | None:
        return round(part / whole, 3) if whole else None

    b_total, b_used = int(briefs["total"]) if briefs else 0, int(briefs["used"]) if briefs else 0
    l_total = int(loops["total"]) if loops else 0
    l_res = int(loops["resolved"]) if loops else 0
    return {
        "days": days,
        "briefs": {
            "total": b_total,
            "used": b_used,
            "share": share(b_used, b_total),
            "target": BRIEFS_TARGET,
        },
        "loops": {
            "total": l_total,
            "resolved": l_res,
            "share": share(l_res, l_total),
            "target": LOOPS_TARGET,
        },
    }
