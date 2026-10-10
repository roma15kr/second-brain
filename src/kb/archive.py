"""Lossless, append-only archive of everything fetched from sources."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from kb.db import Conn


@dataclass(frozen=True)
class RawRecord:
    source_id: str
    external_id: str
    kind: str
    occurred_at: datetime | None
    payload: dict[str, Any] = field(default_factory=dict)
    blob: bytes | None = None

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256(json.dumps(self.payload, sort_keys=True, default=str).encode())
        if self.blob is not None:
            h.update(self.blob)
        return h.hexdigest()


def put(conn: Conn, record: RawRecord) -> int | None:
    """Store a record; returns its id, or None when this exact content is already archived."""
    row = conn.execute(
        """
        INSERT INTO raw_records
            (source_id, external_id, kind, occurred_at, payload, blob, content_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, external_id, content_hash) DO NOTHING
        RETURNING id
        """,
        (
            record.source_id,
            record.external_id,
            record.kind,
            record.occurred_at,
            json.dumps(record.payload, default=str),
            record.blob,
            record.content_hash,
        ),
    ).fetchone()
    return row["id"] if row else None


def get(conn: Conn, record_id: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM raw_records WHERE id = %s", (record_id,)).fetchone()
    if row is None:
        raise KeyError(record_id)
    return row
