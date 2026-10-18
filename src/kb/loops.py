"""Open loops (open-loops spec, design D7).

Needs-reply loops come from the mail revision triage (the AI judged that someone waits for the
owner) and close by themselves when the owner's reply appears in the thread (drafts do not
count). Promise loops come from detection (later task). Every change is a loop_events row.
"""

from __future__ import annotations

from datetime import date, datetime
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


# --- owner actions, listing -----------------------------------------------------------------

LoopAction = Literal["done", "dismiss", "snooze", "due", "reopen"]


class LoopError(ValueError):
    pass


def kyiv_today(now: datetime) -> date:
    from kb.routines import KYIV

    return now.astimezone(KYIV).date()


def act(
    conn: Conn,
    loop_id: int,
    action: LoopAction,
    now: datetime,
    until: date | None = None,
    due: date | None = None,
    by: str = "owner",
) -> None:
    loop = conn.execute("SELECT * FROM loops WHERE id = %s", (loop_id,)).fetchone()
    if loop is None:
        raise LoopError(f"no loop {loop_id}")
    if action == "done":
        conn.execute(
            "UPDATE loops SET status = 'done', closed_at = %s WHERE id = %s", (now, loop_id)
        )
    elif action == "dismiss":
        conn.execute(
            "UPDATE loops SET status = 'dismissed', closed_at = %s WHERE id = %s", (now, loop_id)
        )
        if loop["source_message_key"]:
            conn.execute(
                "INSERT INTO loop_dismissed_sources (source_message_key) VALUES (%s)"
                " ON CONFLICT DO NOTHING",
                (loop["source_message_key"],),
            )
    elif action == "snooze":
        if until is None or until <= kyiv_today(now):
            raise LoopError("snooze needs a future date")
        conn.execute(
            "UPDATE loops SET status = 'snoozed', snoozed_until = %s WHERE id = %s",
            (until, loop_id),
        )
    elif action == "due":
        conn.execute("UPDATE loops SET due_date = %s WHERE id = %s", (due, loop_id))
    elif action == "reopen":
        conn.execute(
            "UPDATE loops SET status = 'open', closed_at = NULL, snoozed_until = NULL"
            " WHERE id = %s",
            (loop_id,),
        )
    else:
        raise LoopError(f"unknown action {action!r}")
    detail = {k: v.isoformat() for k, v in (("until", until), ("due", due)) if v}
    _event(conn, loop_id, action, by, **detail)
    from kb import events

    kind = {"done": "loop_done", "dismiss": "loop_dismissed", "snooze": "loop_snoozed"}.get(action)
    if kind and by == "owner":
        events.record(conn, kind, f"loop:{loop_id}")


def add_manual(
    conn: Conn,
    title: str,
    now: datetime,
    due: date | None = None,
    counterpart: str = "",
    scopes: list[str] | None = None,
) -> int:
    if not title.strip():
        raise LoopError("a loop needs a title")
    row = conn.execute(
        "INSERT INTO loops (kind, title, counterpart, scopes, due_date, opened_at, created_at)"
        " VALUES ('manual', %s, %s, %s, %s, %s, %s) RETURNING id",
        (title.strip()[:200], counterpart[:200], scopes or [], due, now, now),
    ).fetchone()
    assert row is not None
    _event(conn, row["id"], "opened", "owner", source="manual")
    return int(row["id"])


def wake_snoozed(conn: Conn, now: datetime) -> int:
    """Snoozed loops return on their date."""
    rows = conn.execute(
        "UPDATE loops SET status = 'open', snoozed_until = NULL WHERE status = 'snoozed'"
        " AND snoozed_until <= %s RETURNING id",
        (kyiv_today(now),),
    ).fetchall()
    for r in rows:
        _event(conn, r["id"], "woke", "system")
    return len(rows)


def to_dict(row: dict[str, Any], today: date) -> dict[str, Any]:
    due = row["due_date"]
    opened = row["opened_at"]
    return {
        "ref": f"loop:{row['id']}",
        "id": row["id"],
        "kind": row["kind"],
        "title": row["title"],
        "counterpart": row["counterpart"],
        "scopes": list(row["scopes"]),
        "status": row["status"],
        "due_date": due.isoformat() if due else None,
        "overdue": bool(due and row["status"] == "open" and due < today),
        "due_today": bool(due and row["status"] == "open" and due == today),
        "age_days": (today - opened.date()).days if opened else None,
        "snoozed_until": row["snoozed_until"].isoformat() if row["snoozed_until"] else None,
        "item_id": row["item_id"],
        "item_title": row.get("item_title"),
        "link": row["source_link"],
        "opened_at": opened.isoformat() if opened else None,
        "closed_at": row["closed_at"].isoformat() if row["closed_at"] else None,
    }


def list_loops(
    conn: Conn,
    now: datetime,
    status: str = "open",
    kind: str | None = None,
    scope: str | None = None,
    person: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Filtered loops; open ones sorted overdue first, then by due date, then oldest."""
    today = kyiv_today(now)
    rows = conn.execute(
        """
        SELECT l.*, i.title AS item_title FROM loops l LEFT JOIN items i ON i.id = l.item_id
        WHERE l.status = %(status)s
          AND (%(kind)s::text IS NULL OR l.kind = %(kind)s)
          AND (%(scope)s::text IS NULL OR %(scope)s = ANY(l.scopes))
          AND (%(person)s::text IS NULL OR l.counterpart ILIKE '%%' || %(person)s || '%%')
        ORDER BY l.due_date NULLS LAST, l.opened_at
        LIMIT %(limit)s
        """,
        {"status": status, "kind": kind, "scope": scope, "person": person, "limit": limit},
    ).fetchall()
    return [to_dict(r, today) for r in rows]


def for_brief(
    conn: Conn, routine: str, window: tuple[datetime, datetime], now: datetime
) -> dict[str, list[dict[str, Any]]]:
    """Loops a brief should mention: morning → due today/overdue and waiting replies;
    evening → opened and closed today plus replies still owed."""
    today = kyiv_today(now)
    open_rows = list_loops(conn, now, "open")
    out: dict[str, list[dict[str, Any]]] = {}
    due = [lp for lp in open_rows if lp["overdue"] or lp["due_today"]]
    replies = [lp for lp in open_rows if lp["kind"] == "needs_reply"]
    if routine == "morning":
        out["due"] = due
        out["needs_reply"] = replies
    elif routine == "evening":
        start = window[0]
        opened = conn.execute(
            "SELECT l.*, NULL AS item_title FROM loops l WHERE l.created_at >= %s ORDER BY id",
            (start,),
        ).fetchall()
        closed = conn.execute(
            "SELECT l.*, NULL AS item_title FROM loops l WHERE l.closed_at >= %s"
            " AND l.status = 'done' ORDER BY id",
            (start,),
        ).fetchall()
        out["opened"] = [to_dict(r, today) for r in opened]
        out["closed"] = [to_dict(r, today) for r in closed]
        out["needs_reply"] = replies
        out["due"] = due
    return out
