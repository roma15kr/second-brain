"""Turns archived raw records into searchable items."""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import quote

from kb import archive, email_parse, jobs, people, scopes, units
from kb.config import Config, ConfigError, ImapSource, TelegramSource
from kb.connectors import accounts
from kb.connectors.base import get_state, set_state
from kb.db import Conn
from kb.redact import redact_text

log = logging.getLogger(__name__)

# Bump when the way items are built changes; the indexer then re-indexes the whole archive.
# 2: secret redaction. 3: codes before keywords, alphanumeric codes, passwords without ':'.
# 4: values on the next line after the keyword. 5: conversation units (threads, segments).
# 6: scope layers (rules, review decisions, overrides); folder/chat username kept for rules.
# 7: Gmail thread ids and labels. 8: Gmail web deep links per message.
# 9: people identities on messages and items.
INDEX_VERSION = 9


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


def _resolve(conn: Conn, config: Config, facts: scopes.Facts) -> list[str]:
    return scopes.resolver(conn, config).resolve(facts)[0]


def index_email(conn: Conn, config: Config, raw_id: int, raw: dict[str, Any]) -> int | None:
    parsed = email_parse.parse(bytes(raw["blob"]))
    sent = parsed.date or raw["occurred_at"]
    header = f"From: {parsed.sender}\nTo: {', '.join(parsed.recipients)}\n"
    if parsed.attachments:
        header += f"Attachments: {', '.join(parsed.attachments)}\n"
    payload = raw["payload"]
    refs = list(dict.fromkeys([*parsed.references, parsed.in_reply_to]))
    m = units.Message(
        source_id=raw["source_id"],
        message_key=parsed.message_id or raw["external_id"],
        kind="email",
        sent_at=sent,
        body=redact_text(header + "\n" + units.strip_quoted(parsed.body)),
        author=parsed.sender,
        scopes=_resolve(
            conn,
            config,
            scopes.Facts(
                raw["source_id"],
                "email",
                parsed.sender,
                tuple(parsed.participants),
                folder=payload.get("folder"),
                labels=tuple(payload.get("gm_labels") or ()),
            ),
        ),
        participants=parsed.participants,
        subject=redact_text(parsed.subject),
        refs=[r for r in refs if r],
        version=raw["fetched_at"].isoformat(),
        locator=email_locator(
            accounts.effective_config(conn, config), raw["source_id"], payload, parsed.message_id
        ),
        metadata={
            "raw_id": raw_id,
            "folder": payload.get("folder"),
            "labels": payload.get("gm_labels") or [],
            "gm_thrid": payload.get("gm_thrid"),
        },
    )
    keys = [people.email_key(a) for a in parsed.participants]
    for addr, key in zip(parsed.participants, keys, strict=True):
        people.register(conn, [key], parsed.names.get(addr))
    m.identity_keys = keys
    unit = units.assign_email_unit(conn, m)
    units.save(conn, m, unit)
    return units.rebuild(conn, m.source_id, unit)


def email_locator(
    config: Config, source_id: str, payload: dict[str, Any], message_id: str | None
) -> str:
    """Gmail: a web link that opens the message by Message-ID; otherwise an IMAP locator."""
    if payload.get("gm_thrid") and message_id:
        account = ""
        try:
            source = config.source(source_id)
            if isinstance(source, ImapSource):
                account = f"?authuser={quote(source.username(), safe='@')}"
        except ConfigError:
            pass
        mid = quote("rfc822msgid:" + message_id.strip("<>"), safe=":@")
        return f"https://mail.google.com/mail/{account}#search/{mid}"
    return f"imap://{source_id}/{payload.get('folder')};UID={payload.get('uid')}"


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
    sender = p.get("sender_name") or str(p.get("sender_id") or "unknown")
    chat_id = int(p["chat_id"])
    topic = p.get("topic_id") or (p.get("reply_to_msg_id") if p.get("forum_topic") else None)
    reply_to = p.get("reply_to_msg_id")
    if reply_to and reply_to == topic:
        reply_to = None  # posting into a forum topic, not a reply to a message
    m = units.Message(
        source_id=raw["source_id"],
        message_key=f"{chat_id}:{p['msg_id']}",
        kind="tg",
        sent_at=datetime.fromisoformat(p["date"]),
        body=redact_text(f"{sender}: {text}"),
        author=sender,
        scopes=_resolve(
            conn,
            config,
            scopes.Facts(
                raw["source_id"], "tg", sender, (sender,), chat_id, p.get("chat_username")
            ),
        ),
        participants=[sender],
        chat_id=chat_id,
        msg_id=int(p["msg_id"]),
        topic_id=int(topic) if topic else None,
        reply_to=f"{chat_id}:{reply_to}" if reply_to else None,
        version=p.get("edit_date") or p["date"],
        locator=tg_locator(p),
        metadata={
            "chat_title": p.get("chat_title"),
            "chat_username": p.get("chat_username"),
            "peer_type": p.get("peer_type"),
            "reactions": p.get("reactions", 0),
        },
    )
    gap, max_messages, max_hours = 45, 100, 12
    try:
        source = config.source(m.source_id)
        if isinstance(source, TelegramSource):
            gap = source.gap_for(chat_id, p.get("chat_username"))
            max_messages, max_hours = source.max_unit_messages, source.max_unit_hours
    except ConfigError:
        pass
    keys = people.tg_keys(p.get("sender_id"), p.get("sender_name"), p.get("sender_phone"))
    people.register(conn, keys, re.sub(r"\s*\(@[^)]*\)", "", sender).strip() or None)
    m.identity_keys = keys
    unit = units.assign_tg_unit(
        conn, m, timedelta(minutes=gap), max_messages, timedelta(hours=max_hours)
    )
    units.save(conn, m, unit)
    return units.rebuild(conn, m.source_id, unit)


def hide_tg_deleted(conn: Conn, raw: dict[str, Any]) -> None:
    """Hide deleted messages and rebuild their conversations. Without a chat id (private chats,
    basic groups) message ids are account-wide, so they can only refer to non-channel chats."""
    p = raw["payload"]
    rows = conn.execute(
        """
        UPDATE messages SET hidden = true
        WHERE source_id = %(source)s AND kind = 'tg' AND msg_id = ANY(%(ids)s)
          AND CASE WHEN %(chat)s::bigint IS NULL
                   THEN coalesce(metadata->>'peer_type', '') <> 'channel'
                   ELSE chat_id = %(chat)s::bigint END
        RETURNING unit_key
        """,
        {"source": raw["source_id"], "ids": p["msg_ids"], "chat": p.get("chat_id")},
    ).fetchall()
    for unit in {r["unit_key"] for r in rows}:
        units.rebuild(conn, raw["source_id"], unit)


def rebuild(conn: Conn, source_id: str | None = None) -> int:
    """Rebuild messages and search items from the archive (all sources or one), without
    contacting any source. Review decisions (scope rules, overrides) are kept. Records are queued
    in archive order, so newer versions of a message are applied last. Returns records queued."""
    where, params = ("", ()) if source_id is None else ("WHERE source_id = %s", (source_id,))
    conn.execute(f"DELETE FROM messages {where}", params)
    unit_kinds = "kind IN ('email_thread', 'tg_conversation', 'passage')"
    item_where = f"WHERE {unit_kinds}" + ("" if source_id is None else " AND source_id = %s")
    conn.execute(f"DELETE FROM items {item_where}", params)
    conn.execute(
        """
        DELETE FROM jobs WHERE kind = 'index.raw' AND done_at IS NULL
          AND (%s::text IS NULL OR (payload->>'raw_id')::bigint IN
               (SELECT id FROM raw_records WHERE source_id = %s))
        """,
        (source_id, source_id),
    )
    row = conn.execute(
        f"""
        WITH queued AS (
            INSERT INTO jobs (kind, payload)
            SELECT 'index.raw', jsonb_build_object('raw_id', id) FROM raw_records {where}
            ORDER BY id
            RETURNING 1
        )
        SELECT count(*) AS n FROM queued
        """,
        params,
    ).fetchone()
    n = int(row["n"]) if row else 0
    log.info("rebuild %s: queued %d archived records", source_id or "all sources", n)
    return n


def ensure_index_version(conn: Conn) -> int:
    """If items were built by an older indexer, rebuild everything from the archive.
    Returns the number of records queued."""
    state = get_state(conn, "_indexer", "version") or {}
    if int(state.get("version", 0)) >= INDEX_VERSION:
        return 0
    n = rebuild(conn)
    set_state(conn, "_indexer", "version", {"version": INDEX_VERSION})
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
