"""Sync health and pipeline status: what is working, what is behind, what failed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from kb import jobs
from kb.config import Config, ImapSource, TelegramSource
from kb.connectors.base import get_state, set_state
from kb.db import Conn

KEY = "health"
_OWN_KEYS = ("last_ok", "last_error", "last_error_at")


def _now() -> datetime:
    return datetime.now(UTC)


def record_ok(conn: Conn, source_id: str, **detail: Any) -> None:
    state = get_state(conn, source_id, KEY) or {}
    state.update(detail)
    state["last_ok"] = _now().isoformat()
    set_state(conn, source_id, KEY, state)


def record_error(conn: Conn, source_id: str, error: str) -> None:
    state = get_state(conn, source_id, KEY) or {}
    state["last_error"] = error[:500]
    state["last_error_at"] = _now().isoformat()
    set_state(conn, source_id, KEY, state)


def interval_seconds(source: ImapSource | TelegramSource) -> int:
    return source.poll_seconds if isinstance(source, ImapSource) else source.catch_up_seconds


def source_status(conn: Conn, source: ImapSource | TelegramSource, now: datetime) -> dict[str, Any]:
    h = get_state(conn, source.id, KEY) or {}
    last_ok = datetime.fromisoformat(h["last_ok"]) if h.get("last_ok") else None
    err_at = datetime.fromisoformat(h["last_error_at"]) if h.get("last_error_at") else None
    stale = last_ok is None or now - last_ok > timedelta(seconds=3 * interval_seconds(source))
    failing = err_at is not None and (last_ok is None or err_at > last_ok)
    return {
        "source": source.id,
        "type": source.type,
        "healthy": not (stale or failing),
        "last_ok": h.get("last_ok"),
        "last_error": h.get("last_error") if failing else None,
        "last_error_at": h.get("last_error_at") if failing else None,
        "backfilling": bool(h.get("backfilling")),
        "detail": {
            k: v for k, v in h.items() if k not in ("last_ok", "last_error", "last_error_at")
        },
    }


def status(conn: Conn, config: Config) -> dict[str, Any]:
    now = _now()
    q = conn.execute(
        """
        SELECT count(*) FILTER (WHERE done_at IS NULL AND attempts < %(max)s) AS pending,
               count(*) FILTER (WHERE done_at IS NULL AND attempts >= %(max)s) AS failed,
               min(created_at) FILTER (WHERE done_at IS NULL AND attempts < %(max)s) AS oldest
        FROM jobs
        """,
        {"max": jobs.MAX_ATTEMPTS},
    ).fetchone()
    errors = conn.execute(
        "SELECT kind, attempts, left(last_error, 300) AS error FROM jobs "
        "WHERE last_error IS NOT NULL AND done_at IS NULL ORDER BY id DESC LIMIT 5"
    ).fetchall()
    counts = conn.execute(
        "SELECT kind, count(*) AS n FROM items WHERE NOT hidden GROUP BY kind ORDER BY kind"
    ).fetchall()
    archive = conn.execute(
        "SELECT source_id, count(*) AS n, max(fetched_at) AS last "
        "FROM raw_records GROUP BY source_id"
    ).fetchall()
    assert q is not None
    sources = [source_status(conn, s, now) for s in config.sources]
    from kb import distill

    usage = conn.execute(
        "SELECT coalesce(sum(requests), 0) AS r, coalesce(sum(input_tokens), 0) AS i, "
        "coalesce(sum(output_tokens), 0) AS o FROM llm_usage WHERE day = %s",
        (now.date(),),
    ).fetchone()
    emb = conn.execute(
        "SELECT count(*) FILTER (WHERE embedding IS NOT NULL) AS done, "
        "count(*) FILTER (WHERE embedding IS NULL) AS missing FROM items WHERE NOT hidden"
    ).fetchone()
    inflight = conn.execute(
        "SELECT count(*) AS n FROM distill_batches WHERE finished_at IS NULL"
    ).fetchone()
    return {
        "healthy": all(s["healthy"] for s in sources) and q["failed"] == 0,
        "sources": sources,
        "index_queue": {
            "pending": q["pending"],
            "failed": q["failed"],
            "oldest_pending": q["oldest"].isoformat() if q["oldest"] else None,
            "recent_errors": [dict(e) for e in errors],
        },
        "items": {r["kind"]: r["n"] for r in counts},
        "embeddings": {
            "enabled": config.embedding.enabled,
            "model": config.embedding.model,
            "embedded": emb["done"] if emb else 0,
            "missing": emb["missing"] if emb else 0,
        },
        "llm": {
            "enabled": config.llm.enabled,
            "model": config.llm.model(),
            "today": dict(usage) if usage else {},
            "batches_in_flight": inflight["n"] if inflight else 0,
            "estimate_for_pending": distill.cost_estimate(conn, config, now),
        },
        "archive": {
            r["source_id"]: {"records": r["n"], "last_fetched": r["last"].isoformat()}
            for r in archive
        },
    }
