"""Turns archived raw records into searchable items."""

from __future__ import annotations

import json
import logging

from kb import archive, email_parse, jobs
from kb.config import Config, ConfigError
from kb.db import Conn

log = logging.getLogger(__name__)


def index_raw(conn: Conn, config: Config, raw_id: int) -> int:
    raw = archive.get(conn, raw_id)
    if raw["kind"] != "email":
        raise ValueError(f"no indexer for kind {raw['kind']!r}")
    try:
        scopes = list(config.source(raw["source_id"]).scopes)
    except ConfigError:
        scopes = ["unsorted"]
    parsed = email_parse.parse(bytes(raw["blob"]))
    occurred = parsed.date or raw["occurred_at"]
    header = f"From: {parsed.sender}\nTo: {', '.join(parsed.recipients)}\n"
    if parsed.attachments:
        header += f"Attachments: {', '.join(parsed.attachments)}\n"
    payload = raw["payload"]
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,
                           participants, occurred_at, last_activity_at, locator, metadata)
        VALUES (%s, %s, 'email', %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, source_item_key) DO UPDATE SET
            scopes = EXCLUDED.scopes, title = EXCLUDED.title, raw_text = EXCLUDED.raw_text,
            participants = EXCLUDED.participants, occurred_at = EXCLUDED.occurred_at,
            last_activity_at = EXCLUDED.last_activity_at, locator = EXCLUDED.locator,
            metadata = EXCLUDED.metadata, updated_at = now()
        RETURNING id
        """,
        (
            raw["source_id"],
            parsed.message_id or raw["external_id"],
            scopes,
            parsed.subject,
            header + "\n" + parsed.body,
            parsed.participants,
            occurred,
            occurred,
            f"imap://{raw['source_id']}/{payload.get('folder')};UID={payload.get('uid')}",
            json.dumps(
                {
                    "message_id": parsed.message_id,
                    "in_reply_to": parsed.in_reply_to,
                    "references": parsed.references,
                    "raw_ids": [raw_id],
                }
            ),
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def run_once(conn: Conn, config: Config) -> bool:
    """Process one job; returns False when the queue is empty."""
    job = jobs.claim(conn)
    if job is None:
        return False
    try:
        if job["kind"] == "index.raw":
            index_raw(conn, config, int(job["payload"]["raw_id"]))
        else:
            raise ValueError(f"unknown job kind {job['kind']!r}")
    except Exception as exc:
        log.exception("job %s failed", job["id"])
        jobs.fail(conn, job["id"], repr(exc), job["attempts"])
    else:
        jobs.complete(conn, job["id"])
    return True
