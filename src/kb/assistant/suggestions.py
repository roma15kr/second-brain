"""The approval queue (assistant-actions spec: propose, never act alone; design D17).

Every outward action waits here as a suggestion. Approving runs its executor once: a ClickUp task
draft becomes a task (idempotent: the description carries a `[kb:<id>]` marker, so a retry after
a crash finds the task instead of creating a second one) and a loop "owed to me" follows it until
the task is closed.
"""

from __future__ import annotations

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


def listing(conn: Conn, status: str = "proposed", limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT * FROM suggestions WHERE status = %s ORDER BY created_at DESC LIMIT %s",
        (status, limit),
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
