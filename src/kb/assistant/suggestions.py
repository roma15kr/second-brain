"""The approval queue (assistant-actions spec: propose, never act alone; design D17).

Every outward action waits here as a suggestion. Approving runs its executor once: a ClickUp task
draft becomes a task (idempotent: the description carries a `[kb:<id>]` marker, so a retry after
a crash finds the task instead of creating a second one) and a loop "owed to me" follows it until
the task is closed.
"""

from __future__ import annotations

import contextlib
import logging
import os
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from kb.db import Conn

log = logging.getLogger(__name__)


class SuggestionError(ValueError):
    pass


def propose(
    conn: Conn,
    kind: str,
    payload: dict[str, Any],
    reason: str = "",
    refs: list[str] | None = None,
    scopes: list[str] | None = None,
    item_id: int | None = None,
    goal_id: int | None = None,
) -> int:
    row = conn.execute(
        "INSERT INTO suggestions (kind, payload, reason, refs, scopes, item_id, goal_id)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (kind, Jsonb(payload), reason, refs or [], scopes or [], item_id, goal_id),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def reply_draft(conn: Conn, item_id: int, body: str = "", reason: str = "") -> int:
    """A reply suggestion for an email thread; reuses the pending one for the same thread."""
    from kb.assistant import mail

    mail.thread_headers(conn, item_id)  # raises for non-email items
    row = conn.execute(
        "SELECT id FROM suggestions WHERE kind = 'reply_email' AND item_id = %s"
        " AND status = 'proposed'",
        (item_id,),
    ).fetchone()
    if row is not None:
        return int(row["id"])
    scopes_ = conn.execute("SELECT scopes FROM items WHERE id = %s", (item_id,)).fetchone()
    return propose(
        conn,
        "reply_email",
        {"item_id": item_id, "body": body},
        reason=reason or "Reply requested",
        refs=[f"item:{item_id}"],
        scopes=list(scopes_["scopes"]) if scopes_ else [],
        item_id=item_id,
    )


def get(conn: Conn, sid: int) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM suggestions WHERE id = %s", (sid,)).fetchone()
    if row is None:
        raise SuggestionError(f"no suggestion {sid}")
    return dict(row)


def discard(conn: Conn, sid: int, reason: str | None, now: datetime) -> None:
    s = get(conn, sid)
    if s["status"] not in ("proposed", "failed"):
        raise SuggestionError(f"suggestion {sid} is {s['status']}")
    conn.execute(
        "UPDATE suggestions SET status = 'discarded', discard_reason = %s, decided_at = %s"
        " WHERE id = %s",
        (reason, now, sid),
    )


def approve(
    conn: Conn,
    sid: int,
    now: datetime,
    edited: dict[str, Any] | None = None,
    clickup_client: Callable[[], Any] | None = None,
) -> str:
    """Runs the suggestion's executor; returns what was created (e.g. the ClickUp task id)."""
    s = get(conn, sid)
    if s["status"] == "applied":
        return str(s["applied_ref"])
    if s["status"] not in ("proposed", "failed", "approved", "applying"):
        raise SuggestionError(f"suggestion {sid} is {s['status']}")
    payload = {**s["payload"], **(edited or {})}
    conn.execute(
        "UPDATE suggestions SET payload = %s, edited = edited OR %s, status = 'approved',"
        " decided_at = %s, error = NULL WHERE id = %s",
        (Jsonb(payload), bool(edited) and payload != s["payload"], now, sid),
    )
    if s["kind"] == "reply_email":
        # saved by the routines service (it holds the mailbox credentials): apply_mail
        if not (payload.get("body") or "").strip():
            raise SuggestionError("the reply is empty")
        conn.execute(
            "UPDATE suggestions SET payload = payload || %s WHERE id = %s",
            (Jsonb({"action": "draft"}), sid),
        )
        return "queued"
    if s["kind"] in ("task", "delegate"):
        if clickup_client is None:
            raise SuggestionError("ClickUp is not connected")
        try:
            ref = _create_task(conn, sid, payload, clickup_client(), now, s["attempt_started_at"])
        except Exception as e:
            conn.execute(
                "UPDATE suggestions SET status = 'failed', error = %s WHERE id = %s",
                (str(e)[:500], sid),
            )
            raise
        return ref
    raise SuggestionError(f"no executor for {s['kind']} yet")


UNDO_SECONDS = 10


def send_on_tap(
    conn: Conn, sid: int, now: datetime, edited: dict[str, Any] | None = None
) -> datetime:
    """The owner tapped Send on one reply: it is sent after the undo window, unless undone.
    There is deliberately no way to send several at once or on a schedule."""
    s = get(conn, sid)
    if s["kind"] != "reply_email":
        raise SuggestionError("only email replies can be sent")
    if s["status"] not in ("proposed", "failed"):
        raise SuggestionError(f"suggestion {sid} is {s['status']}")
    payload = {**s["payload"], **(edited or {}), "action": "send"}
    if not (payload.get("body") or "").strip():
        raise SuggestionError("the reply is empty")
    send_after = now + timedelta(seconds=UNDO_SECONDS)
    conn.execute(
        "UPDATE suggestions SET payload = %s, edited = edited OR %s, status = 'approved',"
        " decided_at = %s, error = NULL WHERE id = %s",
        (Jsonb(payload), payload.get("body") != s["payload"].get("body"), now, sid),
    )
    conn.execute(
        "INSERT INTO outbox (suggestion_id, send_after) VALUES (%s, %s)"
        " ON CONFLICT (suggestion_id) DO UPDATE SET status = 'pending_send',"
        " send_after = EXCLUDED.send_after, error = NULL",
        (sid, send_after),
    )
    return send_after


def undo_send(conn: Conn, sid: int) -> None:
    row = conn.execute(
        "UPDATE outbox SET status = 'cancelled' WHERE suggestion_id = %s"
        " AND status = 'pending_send' RETURNING id",
        (sid,),
    ).fetchone()
    if row is None:
        raise SuggestionError("too late to undo: the message is being sent or was sent")
    conn.execute(
        "UPDATE suggestions SET status = 'proposed', decided_at = NULL WHERE id = %s", (sid,)
    )


def apply_mail(
    conn: Conn,
    config: Any,
    now: datetime,
    open_imap: Callable[[Any], Any] | None = None,
    open_smtp: Callable[[Any], Any] | None = None,
) -> int:
    """Saves approved replies to their mailbox's Drafts, and sends replies whose undo window
    has passed (once: a send interrupted by a crash is marked failed, never repeated)."""
    from kb.assistant import mail

    imap_opener = open_imap or mail.open_imap
    smtp_opener = open_smtp or mail.open_smtp
    conn.execute(
        "UPDATE outbox SET status = 'failed', error = 'interrupted while sending: check the Sent"
        " folder before sending again' WHERE status = 'sending'"
    )
    conn.execute(
        "UPDATE suggestions s SET status = 'failed', error = o.error FROM outbox o"
        " WHERE o.suggestion_id = s.id AND o.status = 'failed' AND s.status = 'applying'"
    )
    done = 0
    drafts = conn.execute(
        "SELECT * FROM suggestions WHERE kind = 'reply_email' AND status = 'approved'"
        " AND coalesce(payload->>'action', 'draft') = 'draft' ORDER BY decided_at LIMIT 10"
    ).fetchall()
    for s in drafts:
        sid, payload = s["id"], s["payload"]
        _applying(conn, sid, now)
        client = None
        try:
            thread = mail.thread_headers(conn, int(payload["item_id"]))
            box = mail.mailbox(conn, config, thread["source_id"])
            msg = mail.build_reply(conn, sid, payload, box, now)
            client = imap_opener(box)
            ref = mail.save_draft(client, msg, now)
        except Exception as e:
            _failed(conn, sid, e)
            continue
        finally:
            _logout(client)
        _applied(conn, sid, ref)
        done += 1
    due = conn.execute(
        "SELECT o.id AS outbox_id, s.* FROM outbox o JOIN suggestions s ON s.id = o.suggestion_id"
        " WHERE o.status = 'pending_send' AND o.send_after <= %s ORDER BY o.send_after LIMIT 10",
        (now,),
    ).fetchall()
    for s in due:
        sid, payload = s["id"], s["payload"]
        try:  # everything that can fail before the message leaves
            thread = mail.thread_headers(conn, int(payload["item_id"]))
            box = mail.mailbox(conn, config, thread["source_id"])
            msg = mail.build_reply(conn, sid, payload, box, now)
        except Exception as e:
            _send_failed(conn, s["outbox_id"], sid, e)
            continue
        # stored (autocommit) before sending: after a crash the row is failed, never resent
        conn.execute("UPDATE outbox SET status = 'sending' WHERE id = %s", (s["outbox_id"],))
        _applying(conn, sid, now)
        try:
            server = smtp_opener(box)
            try:
                server.send_message(msg)
            finally:
                with contextlib.suppress(Exception):
                    server.quit()
        except Exception as e:
            _send_failed(conn, s["outbox_id"], sid, e)
            continue
        conn.execute(
            "UPDATE outbox SET status = 'sent', sent_at = %s, message_id = %s WHERE id = %s",
            (now, str(msg["Message-ID"]), s["outbox_id"]),
        )
        _applied(conn, sid, str(msg["Message-ID"]))
        from kb import loops

        loops.close_for_item(conn, int(payload["item_id"]), now, via="sent reply")
        if not box.gmail:
            client = None
            try:
                client = imap_opener(box)
                mail.copy_to_sent(client, msg, now)
            except Exception as e:  # the mail is sent; only the copy is missing
                log.warning("sent reply %s not copied to Sent: %s", sid, e)
            finally:
                _logout(client)
        done += 1
    return done


def _applying(conn: Conn, sid: int, now: datetime) -> None:
    conn.execute(
        "UPDATE suggestions SET status = 'applying', attempt_started_at = %s WHERE id = %s",
        (now, sid),
    )


def _applied(conn: Conn, sid: int, ref: str) -> None:
    conn.execute(
        "UPDATE suggestions SET status = 'applied', applied_ref = %s WHERE id = %s", (ref, sid)
    )


def _failed(conn: Conn, sid: int, e: Exception) -> None:
    log.warning("email suggestion %s failed: %s", sid, e)
    conn.execute(
        "UPDATE suggestions SET status = 'failed', error = %s WHERE id = %s", (str(e)[:500], sid)
    )


def _send_failed(conn: Conn, outbox_id: int, sid: int, e: Exception) -> None:
    conn.execute(
        "UPDATE outbox SET status = 'failed', error = %s WHERE id = %s", (str(e)[:500], outbox_id)
    )
    _failed(conn, sid, e)


def _logout(client: Any) -> None:
    if client is not None:
        with contextlib.suppress(Exception):
            client.logout()


def _marker(sid: int) -> str:
    return f"[kb:{sid}]"


def _due_ms(value: str | None) -> int | None:
    if not value:
        return None
    from kb.routines import KYIV

    d = date.fromisoformat(value)
    return int(datetime.combine(d, time(18, 0), tzinfo=KYIV).timestamp() * 1000)


def _create_task(
    conn: Conn,
    sid: int,
    payload: dict[str, Any],
    client: Any,
    now: datetime,
    previous_attempt: datetime | None,
) -> str:
    list_id = payload.get("list_id") or default_list(conn)
    if not list_id:
        raise SuggestionError("choose a ClickUp list (no default list for task drafts)")
    if not str(payload.get("name", "")).strip():
        raise SuggestionError("a task needs a name")
    marker = _marker(sid)
    task: dict[str, Any] | None = None
    if previous_attempt is not None:  # a crash after creating? find the task by its marker
        since = int((previous_attempt - timedelta(minutes=5)).timestamp() * 1000)
        task = next(
            (
                t
                for t in client.recent_tasks(list_id, since)
                if marker in (t.get("description") or t.get("text_content") or "")
            ),
            None,
        )
    if task is None:
        conn.execute(
            "UPDATE suggestions SET status = 'applying', attempt_started_at = %s WHERE id = %s",
            (now, sid),
        )
        emails = [e.lower() for e in payload.get("assignee_emails") or []]
        ids = []
        if emails:
            members = client.list_members(list_id)
            ids = [m["id"] for m in members if (m.get("email") or "").lower() in emails]
        origin = os.environ.get("KB_WEB_ORIGIN", "")
        source = (
            f"\n\nFrom the second brain: {origin}/c/{payload['source_item_id']}"
            if payload.get("source_item_id") and origin
            else ""
        )
        body: dict[str, Any] = {
            "name": str(payload["name"]).strip()[:200],
            "description": f"{payload.get('description', '')}{source}\n\n{marker}".strip(),
            "assignees": ids,
        }
        if (due := _due_ms(payload.get("due_date"))) is not None:
            body["due_date"] = due
            body["due_date_time"] = False
        task = client.create_task(list_id, body)
    task_id = str(task["id"])
    conn.execute(
        "UPDATE suggestions SET status = 'applied', applied_ref = %s WHERE id = %s",
        (task_id, sid),
    )
    _follow_with_loop(conn, sid, payload, task_id)
    return task_id


def _follow_with_loop(conn: Conn, sid: int, payload: dict[str, Any], task_id: str) -> None:
    """The delegated task is owed to the owner until it is closed in ClickUp."""
    from kb import loops

    if conn.execute("SELECT 1 FROM loops WHERE clickup_task_id = %s", (task_id,)).fetchone():
        return
    who = payload.get("assignee_name") or ", ".join(payload.get("assignee_emails") or [])
    row = conn.execute(
        "INSERT INTO loops (kind, title, item_id, counterpart, scopes, due_date, clickup_task_id)"
        " VALUES ('owed_to_me', %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            str(payload["name"])[:200],
            payload.get("source_item_id"),
            who,
            payload.get("scopes") or [],
            date.fromisoformat(payload["due_date"]) if payload.get("due_date") else None,
            task_id,
        ),
    ).fetchone()
    assert row is not None
    loops._event(conn, row["id"], "opened", "system", source="clickup", suggestion=sid)


def default_list(conn: Conn) -> str | None:
    row = conn.execute(
        "SELECT list_id FROM clickup_lists WHERE default_for_drafts LIMIT 1"
    ).fetchone()
    return str(row["list_id"]) if row else None


RECENT = ("approved", "applying", "applied", "failed")


def listing(conn: Conn, status: str = "proposed", limit: int = 100) -> list[dict[str, Any]]:
    """Pending suggestions, or `recent`: decided in the last 7 days and not discarded."""
    statuses = list(RECENT) if status == "recent" else [status]
    rows = conn.execute(
        "SELECT s.*, i.title AS item_title FROM suggestions s LEFT JOIN items i ON i.id = s.item_id"
        " WHERE s.status = ANY(%s) AND (%s OR s.decided_at > now() - interval '7 days')"
        " ORDER BY coalesce(s.decided_at, s.created_at) DESC LIMIT %s",
        (statuses, status != "recent", limit),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "kind": r["kind"],
            "payload": r["payload"],
            "reason": r["reason"],
            "refs": list(r["refs"]),
            "scopes": list(r["scopes"]),
            "item_id": r["item_id"],
            "item_title": r["item_title"],
            "status": r["status"],
            "applied_ref": r["applied_ref"],
            "error": r["error"],
            "created_at": r["created_at"].isoformat(),
        }
        for r in rows
    ]


def clickup_client_factory(conn: Conn) -> Callable[[], Any] | None:
    """A client for the connected ClickUp account (the first one)."""
    from kb.connectors import clickup

    accounts = clickup.accounts(conn)
    if not accounts:
        return None
    token = accounts[0].token
    return lambda: clickup.ClickUpClient(token)
