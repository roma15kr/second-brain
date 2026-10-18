"""Shared connector plumbing: sync cursors and handing archived records to the indexer."""

from __future__ import annotations

import json
from typing import Any

from kb import archive, jobs
from kb.archive import RawRecord
from kb.db import Conn


def get_state(conn: Conn, source_id: str, key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT value FROM sync_state WHERE source_id = %s AND key = %s", (source_id, key)
    ).fetchone()
    return row["value"] if row else None


def set_state(conn: Conn, source_id: str, key: str, value: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO sync_state (source_id, key, value) VALUES (%s, %s, %s)
        ON CONFLICT (source_id, key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()
        """,
        (source_id, key, json.dumps(value)),
    )


def store(conn: Conn, record: RawRecord) -> bool:
    """Archive a record and queue it for indexing. Returns False if it was already archived."""
    record_id = archive.put(conn, record)
    if record_id is None:
        return False
    jobs.enqueue(conn, "index.raw", {"raw_id": record_id})
    return True
