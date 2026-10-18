"""App usage events (design D10): brief opened, rating, item actions. Local only; feeds the
success metric on Status."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from kb.db import Conn

KINDS = {
    "brief_opened",
    "brief_rating",
    "item_opened",
    "loop_done",
    "loop_snoozed",
    "loop_dismissed",
}


def record(
    conn: Conn, kind: str, ref: str, value: dict[str, Any] | None = None, at: datetime | None = None
) -> None:
    if kind not in KINDS:
        raise ValueError(f"unknown event kind {kind!r}; valid: {', '.join(sorted(KINDS))}")
    conn.execute(
        "INSERT INTO app_events (kind, ref, value, at) VALUES (%s, %s, %s, coalesce(%s, now()))",
        (kind, ref, Jsonb(value or {}), at),
    )


def brief_state(conn: Conn, brief_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Per brief: opened (bool) and the latest rating (True/False/None)."""
    refs = [f"brief:{i}" for i in brief_ids]
    out: dict[int, dict[str, Any]] = {i: {"opened": False, "useful": None} for i in brief_ids}
    rows = conn.execute(
        "SELECT DISTINCT ON (ref, kind) ref, kind, value FROM app_events"
        " WHERE ref = ANY(%s) AND kind IN ('brief_opened', 'brief_rating')"
        " ORDER BY ref, kind, at DESC, id DESC",
        (refs,),
    ).fetchall()
    for r in rows:
        bid = int(r["ref"].split(":", 1)[1])
        if r["kind"] == "brief_opened":
            out[bid]["opened"] = True
        else:
            out[bid]["useful"] = bool(r["value"].get("useful"))
    return out
