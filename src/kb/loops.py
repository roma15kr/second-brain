"""Open loops (open-loops spec, design D7).

Needs-reply loops come from the mail revision triage (the AI judged that someone waits for the
owner) and close by themselves when the owner's reply appears in the thread (drafts do not
count). Promise loops come from detection (later task). Every change is a loop_events row.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from psycopg.types.json import Jsonb

from kb.config import Config, ImapSource
from kb.db import Conn

LoopKind = Literal["needs_reply", "i_owe", "owed_to_me", "manual"]
DRAFT_LABEL = "\\Draft"
# A Gmail draft is not a reply: it carries the \Draft label.
NOT_DRAFT = "NOT (coalesce(m.metadata->'labels', '[]'::jsonb) ? '\\Draft')"


# --- the owner's identities -----------------------------------------------------------------


def owner_emails(conn: Conn, config: Config) -> set[str]:
    """Connected mailboxes plus addresses the owner added in Settings."""
    out: set[str] = set()
    for s in config.sources:
        if isinstance(s, ImapSource):
            try:
                out.add(s.username().lower())
            except Exception:  # mailbox credentials not available in this process
                continue
    out.update(a.lower() for a in get_setting(conn, "owner_emails", []))
    return out


def owner_telegram_ids(conn: Conn) -> set[str]:
    """Recorded by the Telegram service at login, plus ids added in Settings."""
    ids = get_setting(conn, "owner_telegram_ids", []) + get_setting(conn, "telegram_self_ids", [])
    return {str(i) for i in ids}


def get_setting(conn: Conn, key: str, default: Any) -> Any:
    row = conn.execute("SELECT value FROM app_settings WHERE key = %s", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn: Conn, key: str, value: Any) -> None:
    conn.execute(
        "INSERT INTO app_settings (key, value) VALUES (%s, %s) ON CONFLICT (key)"
        " DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
        (key, Jsonb(value)),
    )


# --- events ---------------------------------------------------------------------------------


def _event(conn: Conn, loop_id: int, action: str, by: str, **detail: Any) -> None:
    conn.execute(
        "INSERT INTO loop_events (loop_id, action, by, detail) VALUES (%s, %s, %s, %s)",
        (loop_id, action, by, Jsonb(detail)),
    )


# --- needs reply ----------------------------------------------------------------------------


def open_needs_reply(conn: Conn, item_id: int, title: str, now: datetime) -> int | None:
    """Opens a needs-reply loop for a thread (from triage); None if one is already live or the
    owner dismissed this thread's loop before."""
    item = conn.execute(
        """
        SELECT i.scopes, i.locator, m.message_key, m.author, m.sent_at
        FROM items i
        JOIN LATERAL (
            SELECT m.message_key, m.author, m.sent_at FROM messages m
            WHERE m.source_id = i.source_id AND m.unit_key = i.source_item_key AND NOT m.hidden
              AND """
        + NOT_DRAFT
        + """
            ORDER BY m.sent_at DESC LIMIT 1
        ) m ON true
        WHERE i.id = %s
        """,
        (item_id,),
    ).fetchone()
    if item is None:
        return None
    dismissed = conn.execute(
        "SELECT 1 FROM loop_dismissed_sources WHERE source_message_key = %s",
        (item["message_key"],),
    ).fetchone()
    if dismissed:
        return None
    row = conn.execute(
        "INSERT INTO loops (kind, title, item_id, counterpart, scopes, source_message_key,"
        " source_link, opened_at, created_at) VALUES ('needs_reply', %s, %s, %s, %s, %s, %s, %s,"
        " %s) ON CONFLICT DO NOTHING RETURNING id",
        (
            title,
            item_id,
            item["author"] or "",
            item["scopes"],
            item["message_key"],
            item["locator"] if str(item["locator"] or "").startswith("https://") else None,
            item["sent_at"],
            now,
        ),
    ).fetchone()
    if row is None:
        return None
    _event(conn, row["id"], "opened", "system", source="triage")
    return int(row["id"])


def close_answered(conn: Conn, owner: set[str], now: datetime) -> int:
    """Marks needs-reply loops done when the owner has written in the thread after the message
    that opened them. Returns how many closed."""
    if not owner:
        return 0
    rows = conn.execute(
        """
        SELECT l.id, r.message_key
        FROM loops l
        JOIN items i ON i.id = l.item_id
        JOIN LATERAL (
            SELECT m.message_key FROM messages m
            WHERE m.source_id = i.source_id AND m.unit_key = i.source_item_key AND NOT m.hidden
              AND m.sent_at > l.opened_at
              AND lower(substring(m.author from '[^<\\s]+@[^>\\s]+')) = ANY(%s)
              AND """
        + NOT_DRAFT
        + """
            ORDER BY m.sent_at LIMIT 1
        ) r ON true
        WHERE l.kind = 'needs_reply' AND l.status IN ('open', 'snoozed')
        """,
        (sorted(owner),),
    ).fetchall()
    for r in rows:
        conn.execute(
            "UPDATE loops SET status = 'done', closed_at = %s, closing_message_key = %s"
            " WHERE id = %s",
            (now, r["message_key"], r["id"]),
        )
        _event(conn, r["id"], "done", "system", closing_message_key=r["message_key"])
    return len(rows)


def close_for_item(conn: Conn, item_id: int, now: datetime, by: str = "owner") -> int:
    """Owner marked a conversation done (e.g. in the Inbox): its live needs-reply loop closes."""
    rows = conn.execute(
        "UPDATE loops SET status = 'done', closed_at = %s WHERE item_id = %s"
        " AND kind = 'needs_reply' AND status IN ('open', 'snoozed') RETURNING id",
        (now, item_id),
    ).fetchall()
    for r in rows:
        _event(conn, r["id"], "done", by, via="inbox")
    return len(rows)
