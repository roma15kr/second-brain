"""Status page (web-dashboard spec): sync health, routine runs, queue, backups, AI spend and the
28-day usefulness metric."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from kb import distill, health, metrics, settings_store
from kb.api.deps import get_conn
from kb.assistant import proactive
from kb.connectors import accounts
from kb.db import Conn

router = APIRouter()
Db = Annotated[Conn, Depends(get_conn)]


@router.get("/api/status")
def status(request: Request, conn: Db) -> dict[str, Any]:
    config = request.app.state.config
    now = datetime.now(UTC)
    runs = conn.execute(
        "SELECT routine, slot, status, delayed, attempts, error, finished_at FROM routine_runs"
        " ORDER BY slot DESC, id DESC LIMIT 20"
    ).fetchall()
    month_start = now.date().replace(day=1)
    by_purpose = conn.execute(
        "SELECT purpose, model, sum(input_tokens) AS i, sum(output_tokens) AS o FROM llm_usage"
        " WHERE day >= %s GROUP BY purpose, model ORDER BY purpose",
        (month_start,),
    ).fetchall()
    return {
        "system": health.status(conn, accounts.effective_config(conn, config)),
        "routine_runs": [
            {
                "routine": r["routine"],
                "slot": r["slot"].isoformat(),
                "status": r["status"],
                "delayed": r["delayed"],
                "attempts": r["attempts"],
                "error": r["error"],
                "finished_at": r["finished_at"].isoformat() if r["finished_at"] else None,
            }
            for r in runs
        ],
        "ai": {
            "month_spend_usd": round(distill.month_spend_usd(conn, now.date()), 2),
            "budget_usd": settings_store.budget_usd(conn, config),
            "by_purpose": [
                {
                    "purpose": r["purpose"],
                    "model": r["model"],
                    "usd": round(
                        distill.cost_usd(r["model"], distill.Usage(int(r["i"]), int(r["o"]))), 2
                    ),
                }
                for r in by_purpose
            ],
        },
        "usefulness": metrics.usefulness(conn, now),
        "suggestions": proactive.acceptance(conn, now),
    }
