"""Turns archived raw records into searchable items."""

from __future__ import annotations

import json
import logging
from typing import Any

from kb import archive, email_parse, jobs
from kb.config import Config, ConfigError, TelegramSource
from kb.connectors.base import get_state, set_state
from kb.db import Conn
from kb.redact import redact_text

log = logging.getLogger(__name__)

# Bump when the way items are built changes; the indexer then re-indexes the whole archive.
# 2: secret redaction.
INDEX_VERSION = 2


def index_raw(conn: Conn, config: Config, raw_id: int) -> int | None:
    raw = archive.get(conn, raw_id)
    if raw["kind"] == "email":
        return index_email(conn, config, raw_id, raw)
    if raw["kind"] == "tg_message":
        return index_tg_message(conn, config, raw)
    if raw["kind"] == "tg_delete":
        hide_tg_deleted(conn, raw)
        return None
    raise ValueError(f"no indexer for kind {raw['kind']!r}")


def index_email(conn: Conn, config: Config, raw_id: int, raw: dict[str, Any]) -> int:
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
            redact_text(parsed.subject),
            redact_text(header + "\n" + parsed.body),
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


def tg_locator(payload: dict[str, Any]) -> str:
    chat_id, msg_id = int(payload["chat_id"]), int(payload["msg_id"])
    if payload.get("chat_username"):
        return f"https://t.me/{payload['chat_username']}/{msg_id}"
    if payload.get("peer_type") == "channel" and str(chat_id).startswith("-100"):
        return f"https://t.me/c/{str(chat_id)[4:]}/{msg_id}"
    return f"telegram://chat/{chat_id}/{msg_id}"


def index_tg_message(conn: Conn, config: Config, raw: dict[str, Any]) -> int | None:
    p = raw["payload"]
    text = (p.get("text") or "").strip()
    if not text:
        return None  # media without caption: archived, nothing to search yet
    try:
        source = config.source(raw["source_id"])
        scopes = (
            source.scopes_for(p["chat_id"], p.get("chat_username"))
            if isinstance(source, TelegramSource)
            else list(source.scopes)
        )
    except ConfigError:
        scopes = ["unsorted"]
    sender = p.get("sender_name") or str(p.get("sender_id") or "unknown")
    version = p.get("edit_date") or p["date"]
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,
                           participants, occurred_at, last_activity_at, locator, metadata)
        VALUES (%s, %s, 'tg_message', %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, source_item_key) DO UPDATE SET
            scopes = EXCLUDED.scopes, title = EXCLUDED.title, raw_text = EXCLUDED.raw_text,
            participants = EXCLUDED.participants, last_activity_at = EXCLUDED.last_activity_at,
            locator = EXCLUDED.locator, metadata = EXCLUDED.metadata, updated_at = now()
        WHERE items.metadata->>'version' <= EXCLUDED.metadata->>'version'
        RETURNING id
        """,
        (
            raw["source_id"],
            f"{p['chat_id']}:{p['msg_id']}",
            scopes,
            p.get("chat_title"),
            redact_text(f"{sender}: {text}"),
            [sender],
            p["date"],
            version,
            tg_locator(p),
            json.dumps(
                {
                    "chat_id": p["chat_id"],
                    "msg_id": p["msg_id"],
                    "peer_type": p.get("peer_type"),
                    "reply_to_msg_id": p.get("reply_to_msg_id"),
                    "topic_id": p.get("topic_id"),
                    "reactions": p.get("reactions", 0),
                    "version": version,
                }
            ),
        ),
    ).fetchone()
    return int(row["id"]) if row else None


def hide_tg_deleted(conn: Conn, raw: dict[str, Any]) -> None:
    """Hide deleted messages. Without a chat id (private chats, basic groups) message ids are
    account-wide, so they can only refer to non-channel chats."""
    p = raw["payload"]
    conn.execute(
        """
        UPDATE items SET hidden = true, updated_at = now()
        WHERE source_id = %(source)s AND kind = 'tg_message'
          AND (metadata->>'msg_id')::bigint = ANY(%(ids)s)
          AND CASE WHEN %(chat)s::bigint IS NULL
                   THEN metadata->>'peer_type' <> 'channel'
                   ELSE (metadata->>'chat_id')::bigint = %(chat)s::bigint END
        """,
        {"source": raw["source_id"], "ids": p["msg_ids"], "chat": p.get("chat_id")},
    )


def ensure_index_version(conn: Conn) -> int:
    """If items were built by an older indexer, queue every archived record for re-indexing.

    Records are queued in archive order, so newer versions of a message are applied last.
    Returns the number of records queued.
    """
    state = get_state(conn, "_indexer", "version") or {}
    if int(state.get("version", 0)) >= INDEX_VERSION:
        return 0
    row = conn.execute(
        """
        WITH queued AS (
            INSERT INTO jobs (kind, payload)
            SELECT 'index.raw', jsonb_build_object('raw_id', id) FROM raw_records ORDER BY id
            RETURNING 1
        )
        SELECT count(*) AS n FROM queued
        """
    ).fetchone()
    set_state(conn, "_indexer", "version", {"version": INDEX_VERSION})
    n = int(row["n"]) if row else 0
    log.info("index version %s: queued %d archived records for re-indexing", INDEX_VERSION, n)
    return n


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
