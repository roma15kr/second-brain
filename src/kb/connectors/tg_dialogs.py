"""Telegram dialogs chosen and marked in the web OS (source-ingestion and connectors specs).

The Telegram service lists the owner's dialogs (metadata only, read-only) into tg_dialogs. New
dialogs wait in "to mark" and nothing from them is stored until included. Dialogs on the config
allowlist are imported as included the first time they are seen. A mark is a chat scope rule, so
changing it re-labels the dialog's existing conversations.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from kb import scopes
from kb.config import Config, TelegramChat, TelegramSource
from kb.db import Conn


def upsert_dialogs(
    conn: Conn, source: TelegramSource, dialogs: list[tuple[Any, datetime | None]]
) -> int:
    """dialogs: (ChatInfo, last message time). Returns how many are new."""
    new = 0
    for info, last in dialogs:
        configured = source.chat_config(info.chat_id, info.username)
        row = conn.execute(
            """
            INSERT INTO tg_dialogs (chat_id, source_id, title, username, peer_type,
                                    last_message_at, included, scopes)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (chat_id) DO UPDATE SET title = EXCLUDED.title,
                username = EXCLUDED.username, peer_type = EXCLUDED.peer_type,
                last_message_at = EXCLUDED.last_message_at, seen_at = now()
            RETURNING (xmax = 0) AS inserted
            """,
            (
                info.chat_id,
                source.id,
                info.title,
                info.username,
                info.peer_type,
                last,
                True if configured else None,
                list(configured.scopes or []) if configured else [],
            ),
        ).fetchone()
        new += 1 if row and row["inserted"] else 0
    return new


def effective_source(conn: Conn, source: TelegramSource) -> TelegramSource:
    """The source with today's allowlist: dialogs included in the web OS, plus configured chats
    the owner has not ignored there."""
    rows = conn.execute(
        "SELECT chat_id, username, included FROM tg_dialogs WHERE source_id = %s", (source.id,)
    ).fetchall()
    ignored = {r["chat_id"] for r in rows if r["included"] is False}
    ignored_names = {(r["username"] or "").lower() for r in rows if r["included"] is False}
    chats: list[TelegramChat] = []
    for c in source.chats:
        ref = str(c.chat).lstrip("@").lower()
        if (ref.lstrip("-").isdigit() and int(ref) in ignored) or ref in ignored_names:
            continue
        chats.append(c)
    configured = {c.chat for c in chats}
    for r in rows:
        if r["included"] and r["chat_id"] not in configured:
            chats.append(TelegramChat(chat=r["chat_id"]))
    return source.model_copy(update={"chats": chats})


def set_dialog(
    conn: Conn,
    config: Config,
    chat_id: int,
    included: bool | None = None,
    marks: list[str] | None = None,
) -> int:
    """Include/ignore a dialog and/or mark it; returns messages re-labelled."""
    row = conn.execute("SELECT * FROM tg_dialogs WHERE chat_id = %s", (chat_id,)).fetchone()
    if row is None:
        raise scopes.ReviewError(f"no Telegram dialog {chat_id}")
    if included is not None:
        conn.execute(
            "UPDATE tg_dialogs SET included = %s, updated_at = now() WHERE chat_id = %s",
            (included, chat_id),
        )
    changed = 0
    if marks is not None:
        if marks:
            scopes.validate_scopes(marks, scopes.known(conn))
            scopes.set_rule(conn, "chat", str(chat_id), marks)
        else:
            scopes.set_rule(conn, "chat", str(chat_id), None)
        conn.execute(
            "UPDATE tg_dialogs SET scopes = %s, updated_at = now() WHERE chat_id = %s",
            (marks, chat_id),
        )
        changed = scopes.rescope(conn, config, "chat_id = %s", (chat_id,))
    return changed


def listing(conn: Conn) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT chat_id, title, username, peer_type, last_message_at, included, scopes"
        " FROM tg_dialogs ORDER BY last_message_at DESC NULLS LAST"
    ).fetchall()
    counts = {
        r["chat_id"]: r["n"]
        for r in conn.execute(
            "SELECT chat_id, count(*) AS n FROM messages WHERE kind = 'tg'"
            " AND sent_at > now() - interval '7 days' GROUP BY chat_id"
        )
    }

    def view(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "chat_id": r["chat_id"],
            "title": r["title"],
            "username": r["username"],
            "type": r["peer_type"],
            "last_message_at": r["last_message_at"].isoformat() if r["last_message_at"] else None,
            "scopes": list(r["scopes"]),
            "messages_7d": counts.get(r["chat_id"], 0),
        }

    return {
        "to_mark": [view(r) for r in rows if r["included"] is None],
        "included": [view(r) for r in rows if r["included"]],
        "ignored": [view(r) for r in rows if r["included"] is False],
    }
