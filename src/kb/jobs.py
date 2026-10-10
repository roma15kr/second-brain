"""A small Postgres job queue (FOR UPDATE SKIP LOCKED)."""

from __future__ import annotations

import json
from typing import Any

from kb.db import Conn

MAX_ATTEMPTS = 5


def enqueue(conn: Conn, kind: str, payload: dict[str, Any]) -> int:
    row = conn.execute(
        "INSERT INTO jobs (kind, payload) VALUES (%s, %s) RETURNING id",
        (kind, json.dumps(payload)),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def claim(conn: Conn) -> dict[str, Any] | None:
    return conn.execute(
        """
        UPDATE jobs SET locked_at = now(), attempts = attempts + 1
        WHERE id = (
            SELECT id FROM jobs
            WHERE done_at IS NULL AND run_after <= now() AND attempts < %s
              AND (locked_at IS NULL OR locked_at < now() - interval '10 minutes')
            ORDER BY run_after, id
            FOR UPDATE SKIP LOCKED
            LIMIT 1
        )
        RETURNING id, kind, payload, attempts
        """,
        (MAX_ATTEMPTS,),
    ).fetchone()


def complete(conn: Conn, job_id: int) -> None:
    conn.execute("UPDATE jobs SET done_at = now(), locked_at = NULL WHERE id = %s", (job_id,))


def fail(conn: Conn, job_id: int, error: str, attempts: int) -> None:
    conn.execute(
        """
        UPDATE jobs SET locked_at = NULL, last_error = %s,
            run_after = now() + make_interval(secs => %s)
        WHERE id = %s
        """,
        (error[:2000], 30 * 2**attempts, job_id),
    )
