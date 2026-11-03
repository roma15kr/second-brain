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
        "moderate": _to_moderate(conn),
        "mentions": _mentions(conn),
    }


# what the Today screen shows first (web-redesign-v1): proposals waiting and new mentions
DIRECT = ("mentioned", "assigned", "comment_assigned", "chat_direct", "team_mentioned",
          "team_assigned", "group_mentioned", "group_assigned")  # fmt: skip


def _to_moderate(conn: Conn) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM suggestions WHERE status = 'proposed'"
        " AND NOT coalesce((payload->>'ai_pending')::boolean, false)"
    ).fetchone()
    return int(row["n"]) if row else 0


def _mentions(conn: Conn, limit: int = 5) -> list[dict[str, Any]]:
    """ClickUp items for the owner or the team from the last two days, newest first."""
    from kb.connectors import clickup

    rows = conn.execute(
        """
        SELECT n.kind, n.actor, n.subject, n.item_id, coalesce(n.event_at, n.created_at) AS at,
               i.title, a.settings
        FROM clickup_notifications n LEFT JOIN items i ON i.id = n.item_id
        JOIN connector_accounts a ON a.id = n.account_id
        WHERE n.kind = ANY(%s) AND n.created_at > now() - interval '2 days'
        ORDER BY coalesce(n.event_at, n.created_at) DESC LIMIT %s
        """,
        (list(DIRECT), limit),
    ).fetchall()
    return [
        {
            "text": clickup.headline_text(
                r["kind"],
                r["actor"],
                (r["settings"] or {}).get("group_name") or clickup.DEFAULT_GROUP,
                r["subject"],
            ).removeprefix("ClickUp: "),
            "title": r["title"],
            "item_id": r["item_id"],
            "at": r["at"].isoformat(),
        }
        for r in rows
    ]
