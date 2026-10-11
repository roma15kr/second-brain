"""Conversation units: email threads and Telegram conversations built from `messages` rows.

A unit is the search item. Whenever a message is added, edited, hidden or moved, its unit is
rebuilt from all of its visible messages.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from kb.db import Conn

SUBJECT_FALLBACK_DAYS = 30
MAX_MESSAGE_CHARS = 20_000
MAX_UNIT_CHARS = 400_000

_SUBJECT_PREFIX = re.compile(
    r"^\s*((re|fw|fwd|aw|wg|sv|отв|ответ|відп|відповідь|пер|переслано)\s*(\[\d+\]|\(\d+\))?\s*:\s*)+",
    re.IGNORECASE,
)
_QUOTE_START = re.compile(
    r"^(On .{0,200} wrote:|-{2,}\s*Original Message\s*-{2,}|.{0,120}(пише|пишет|написав|написал"
    r"|написала|писал\(\u0430\)):)\s*$",
    re.MULTILINE,
)


def normalize_subject(subject: str | None) -> str:
    s = _SUBJECT_PREFIX.sub("", subject or "")
    return re.sub(r"\s+", " ", s).strip().lower()


def strip_quoted(body: str) -> str:
    """Drop the quoted previous message from an email reply (it is indexed on its own)."""
    m = _QUOTE_START.search(body)
    if m and m.start() > 0:
        body = body[: m.start()]
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">"))


@dataclass
class Message:
    source_id: str
    message_key: str
    kind: str  # 'email' | 'tg'
    sent_at: datetime
    body: str
    author: str | None
    scopes: list[str]
    participants: list[str] = field(default_factory=list)
    subject: str | None = None
    refs: list[str] = field(default_factory=list)
    chat_id: int | None = None
    msg_id: int | None = None
    topic_id: int | None = None
    reply_to: str | None = None
    version: str = ""
    locator: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def existing_unit(conn: Conn, source_id: str, message_key: str) -> str | None:
    row = conn.execute(
        "SELECT unit_key FROM messages WHERE source_id = %s AND message_key = %s",
        (source_id, message_key),
    ).fetchone()
    return row["unit_key"] if row else None


def save(conn: Conn, m: Message, unit_key: str) -> bool:
    """Insert or update a message (older versions never overwrite newer). Returns True if
    the stored row changed."""
    row = conn.execute(
        """
        INSERT INTO messages (source_id, message_key, kind, unit_key, scopes, chat_id, msg_id,
            topic_id, reply_to, refs, subject, subject_norm, author, participants, sent_at, body,
            version, locator, metadata)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, message_key) DO UPDATE SET
            scopes = EXCLUDED.scopes, body = EXCLUDED.body, version = EXCLUDED.version,
            author = EXCLUDED.author, participants = EXCLUDED.participants,
            subject = EXCLUDED.subject, subject_norm = EXCLUDED.subject_norm,
            locator = EXCLUDED.locator, metadata = EXCLUDED.metadata
        WHERE messages.version <= EXCLUDED.version
        RETURNING id
        """,
        (
            m.source_id,
            m.message_key,
            m.kind,
            unit_key,
            m.scopes,
            m.chat_id,
            m.msg_id,
            m.topic_id,
            m.reply_to,
            m.refs,
            m.subject,
            normalize_subject(m.subject),
            m.author,
            m.participants,
            m.sent_at,
            m.body[:MAX_MESSAGE_CHARS],
            m.version,
            m.locator,
            json.dumps(m.metadata, default=str),
        ),
    ).fetchone()
    return row is not None


# --- email threads ------------------------------------------------------------------------


def assign_email_unit(conn: Conn, m: Message) -> str:
    """Gmail: Gmail's own thread id. Otherwise thread by References/In-Reply-To (both directions),
    else by normalized subject with shared participants within 30 days. Merges threads that turn
    out to be one."""
    current = existing_unit(conn, m.source_id, m.message_key)
    thrid = m.metadata.get("gm_thrid")
    if thrid:
        target = f"gmail:{thrid}"
        if current and current != target:
            # An earlier copy (e.g. from INBOX before All Mail) was threaded by headers.
            merge_units(conn, m.source_id, target, [current])
        return target
    if current:
        return current
    related = conn.execute(
        """
        SELECT DISTINCT ON (unit_key) unit_key, sent_at FROM messages
        WHERE source_id = %(s)s AND kind = 'email'
          AND (message_key = ANY(%(refs)s) OR %(key)s = ANY(refs))
        ORDER BY unit_key, sent_at
        """,
        {"s": m.source_id, "refs": m.refs, "key": m.message_key},
    ).fetchall()
    subject_norm = normalize_subject(m.subject)
    if not related and subject_norm:
        related = conn.execute(
            """
            SELECT unit_key, sent_at FROM messages
            WHERE source_id = %(s)s AND kind = 'email' AND subject_norm = %(subj)s
              AND sent_at BETWEEN %(t)s - %(d)s AND %(t)s + %(d)s
              AND participants && %(p)s
            ORDER BY abs(extract(epoch FROM sent_at - %(t)s)) LIMIT 1
            """,
            {
                "s": m.source_id,
                "subj": subject_norm,
                "t": m.sent_at,
                "d": timedelta(days=SUBJECT_FALLBACK_DAYS),
                "p": m.participants,
            },
        ).fetchall()
    if not related:
        return f"email:{m.message_key}"
    related.sort(key=lambda r: r["sent_at"])
    keep = related[0]["unit_key"]
    merge_units(conn, m.source_id, keep, [r["unit_key"] for r in related[1:]])
    return str(keep)


def merge_units(conn: Conn, source_id: str, keep: str, others: list[str]) -> None:
    others = [o for o in others if o != keep]
    if not others:
        return
    conn.execute(
        "UPDATE messages SET unit_key = %s WHERE source_id = %s AND unit_key = ANY(%s)",
        (keep, source_id, others),
    )
    conn.execute(
        "DELETE FROM items WHERE source_id = %s AND (source_item_key = ANY(%s) "
        "OR (kind = 'passage' AND metadata->>'unit_key' = ANY(%s)))",
        (source_id, others, others),
    )


# --- Telegram conversations ---------------------------------------------------------------


def assign_tg_unit(
    conn: Conn,
    m: Message,
    gap: timedelta,
    max_messages: int,
    max_span: timedelta,
) -> str:
    """Reply → the replied message's conversation; otherwise continue the latest conversation
    in the same chat/topic unless the silence gap or size/span limits are exceeded."""
    current = existing_unit(conn, m.source_id, m.message_key)
    if current:
        return current
    if m.reply_to:
        row = conn.execute(
            "SELECT unit_key FROM messages WHERE source_id = %s AND message_key = %s",
            (m.source_id, m.reply_to),
        ).fetchone()
        if row:
            return str(row["unit_key"])
    prev = conn.execute(
        """
        SELECT unit_key, sent_at FROM messages
        WHERE source_id = %s AND kind = 'tg' AND chat_id = %s
          AND topic_id IS NOT DISTINCT FROM %s AND sent_at <= %s
        ORDER BY sent_at DESC, msg_id DESC LIMIT 1
        """,
        (m.source_id, m.chat_id, m.topic_id, m.sent_at),
    ).fetchone()
    if prev and m.sent_at - prev["sent_at"] <= gap:
        stats = conn.execute(
            "SELECT count(*) AS n, min(sent_at) AS first FROM messages "
            "WHERE source_id = %s AND unit_key = %s",
            (m.source_id, prev["unit_key"]),
        ).fetchone()
        assert stats is not None
        if stats["n"] < max_messages and m.sent_at - stats["first"] <= max_span:
            return str(prev["unit_key"])
    return f"tg:{m.chat_id}:{m.topic_id or 0}:{m.msg_id}"


# --- rebuilding units ---------------------------------------------------------------------


def _fmt(t: datetime) -> str:
    return t.strftime("%Y-%m-%d %H:%M")


def rebuild(conn: Conn, source_id: str, unit_key: str) -> int | None:
    """Rebuild the search item for a unit from its visible messages; hide it if none remain."""
    msgs = conn.execute(
        "SELECT * FROM messages WHERE source_id = %s AND unit_key = %s AND NOT hidden "
        "ORDER BY sent_at, id",
        (source_id, unit_key),
    ).fetchall()
    if not msgs:
        conn.execute(
            "UPDATE items SET hidden = true, updated_at = now() "
            "WHERE source_id = %s AND (source_item_key = %s "
            "OR (kind = 'passage' AND metadata->>'unit_key' = %s))",
            (source_id, unit_key, unit_key),
        )
        return None
    first, last = msgs[0], msgs[-1]
    is_email = first["kind"] == "email"
    parts: list[str] = []
    for msg in msgs:
        if is_email:
            parts.append(f"--- {_fmt(msg['sent_at'])}\n{msg['body']}")
        else:
            parts.append(f"[{_fmt(msg['sent_at'])}] {msg['body']}")
    text = "\n\n".join(parts) if is_email else "\n".join(parts)
    participants: list[str] = []
    scopes: list[str] = []
    for msg in msgs:
        for p in msg["participants"]:
            if p and p not in participants:
                participants.append(p)
        for s in msg["scopes"]:
            if s not in scopes:
                scopes.append(s)
    if len(scopes) > 1 and "unsorted" in scopes:
        scopes.remove("unsorted")
    override = conn.execute(
        "SELECT scopes FROM scope_overrides WHERE source_id = %s AND unit_key = %s",
        (source_id, unit_key),
    ).fetchone()
    if override:
        scopes = list(override["scopes"])
    title = first["subject"] if is_email else (first["metadata"].get("chat_title") or "")
    metadata = {
        "message_count": len(msgs),
        "first_message": first["message_key"],
        "last_message": last["message_key"],
        "chat_id": first["chat_id"],
        "topic_id": first["topic_id"],
    }
    from kb import distill

    text = text[:MAX_UNIT_CHARS]
    chash = distill.content_hash(title, text)
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,
                           participants, occurred_at, last_activity_at, locator, metadata,
                           content_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, source_item_key) DO UPDATE SET
            kind = EXCLUDED.kind, scopes = EXCLUDED.scopes, title = EXCLUDED.title,
            raw_text = EXCLUDED.raw_text, participants = EXCLUDED.participants,
            occurred_at = EXCLUDED.occurred_at, last_activity_at = EXCLUDED.last_activity_at,
            locator = EXCLUDED.locator, metadata = EXCLUDED.metadata, hidden = false,
            content_hash = EXCLUDED.content_hash, updated_at = now()
        RETURNING id
        """,
        (
            source_id,
            unit_key,
            "email_thread" if is_email else "tg_conversation",
            scopes,
            title,
            text,
            participants,
            first["sent_at"],
            last["sent_at"],
            first["locator"],
            json.dumps(metadata),
            chash,
        ),
    ).fetchone()
    assert row is not None
    distill.reattach(conn, source_id, unit_key, chash, scopes)
    from kb import passages

    unit = conn.execute(
        "SELECT id, source_id, source_item_key, scopes, title, question FROM items WHERE id = %s",
        (row["id"],),
    ).fetchone()
    assert unit is not None
    passages.build_for_unit(conn, unit)
    return int(row["id"])


def unit_messages(conn: Conn, item_id: int, offset: int, limit: int) -> dict[str, Any]:
    """A unit with one page of its messages (oldest first)."""
    item = conn.execute("SELECT * FROM items WHERE id = %s AND NOT hidden", (item_id,)).fetchone()
    if item is None:
        raise KeyError(item_id)
    total = conn.execute(
        "SELECT count(*) AS n FROM messages WHERE source_id = %s AND unit_key = %s AND NOT hidden",
        (item["source_id"], item["source_item_key"]),
    ).fetchone()
    rows = conn.execute(
        "SELECT message_key, author, sent_at, body, locator FROM messages "
        "WHERE source_id = %s AND unit_key = %s AND NOT hidden ORDER BY sent_at, id "
        "OFFSET %s LIMIT %s",
        (item["source_id"], item["source_item_key"], offset, limit),
    ).fetchall()
    n = int(total["n"]) if total else 0
    return {
        "item": item,
        "messages": rows,
        "total": n,
        "next_offset": offset + limit if offset + limit < n else None,
    }
