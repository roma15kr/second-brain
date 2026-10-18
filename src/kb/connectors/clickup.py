"""ClickUp (clickup-integration spec, design D14).

Reads the owner's chosen lists with a personal API token: tasks changed since the list's cursor
(`date_updated_gt`) and their comments, every few minutes. A task with its comments is one
searchable item, marked by its list; assignees and commenters are linked to people by email.
Writes only one thing: a new task from a draft the owner approved. Respects the per-token rate
limit (429 → pause until the reset time, resume from the saved cursor).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from psycopg.types.json import Jsonb

from kb import archive, people
from kb.db import Conn
from kb.redact import redact_text

log = logging.getLogger(__name__)

API = "https://api.clickup.com/api/v2"
PAGE_LIMIT = 10  # pages per list per cycle (100 tasks each)
CLOSED_TYPES = {"closed", "done"}


class ClickUpError(RuntimeError):
    pass


class RateLimited(ClickUpError):
    def __init__(self, reset_at: float) -> None:
        super().__init__(f"ClickUp rate limit reached; resets at {reset_at:.0f}")
        self.reset_at = reset_at


class ClickUpClient:
    def __init__(self, token: str, transport: httpx.BaseTransport | None = None) -> None:
        self.http = httpx.Client(
            base_url=API, headers={"Authorization": token}, timeout=30, transport=transport
        )

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        r = self.http.request(method, path, **kw)
        if r.status_code == 429:
            reset = float(r.headers.get("X-RateLimit-Reset") or datetime.now(UTC).timestamp() + 60)
            raise RateLimited(reset)
        if r.status_code in (401, 403):
            raise ClickUpError(f"ClickUp refused the token ({r.status_code}): {r.text[:200]}")
        if r.status_code >= 400:
            raise ClickUpError(f"ClickUp {method} {path} failed ({r.status_code}): {r.text[:200]}")
        return r.json()

    def user(self) -> dict[str, Any]:
        return dict(self._req("GET", "/user")["user"])

    def teams(self) -> list[dict[str, Any]]:
        return list(self._req("GET", "/team")["teams"])

    def spaces(self, team_id: str) -> list[dict[str, Any]]:
        return list(
            self._req("GET", f"/team/{team_id}/space", params={"archived": "false"})["spaces"]
        )

    def folders(self, space_id: str) -> list[dict[str, Any]]:
        return list(
            self._req("GET", f"/space/{space_id}/folder", params={"archived": "false"})["folders"]
        )

    def folderless_lists(self, space_id: str) -> list[dict[str, Any]]:
        return list(
            self._req("GET", f"/space/{space_id}/list", params={"archived": "false"})["lists"]
        )

    def tasks(
        self, list_id: str, updated_gt_ms: int, page: int
    ) -> tuple[list[dict[str, Any]], bool]:
        data = self._req(
            "GET",
            f"/list/{list_id}/task",
            params={
                "archived": "false",
                "include_closed": "true",
                "subtasks": "true",
                "order_by": "updated",
                "reverse": "true",
                "date_updated_gt": str(updated_gt_ms),
                "page": str(page),
            },
        )
        return list(data.get("tasks") or []), bool(data.get("last_page", True))

    def comments(self, task_id: str) -> list[dict[str, Any]]:
        return list(self._req("GET", f"/task/{task_id}/comment").get("comments") or [])

    def create_task(self, list_id: str, body: dict[str, Any]) -> dict[str, Any]:
        return dict(self._req("POST", f"/list/{list_id}/task", json=body))

    def list_members(self, list_id: str) -> list[dict[str, Any]]:
        return list(self._req("GET", f"/list/{list_id}/member").get("members") or [])

    def recent_tasks(self, list_id: str, created_gt_ms: int) -> list[dict[str, Any]]:
        data = self._req(
            "GET",
            f"/list/{list_id}/task",
            params={"include_closed": "true", "date_created_gt": str(created_gt_ms)},
        )
        return list(data.get("tasks") or [])


# --- account and lists -----------------------------------------------------------------------


@dataclass
class Account:
    id: int
    token: str
    team_id: str


def accounts(conn: Conn) -> list[Account]:
    from kb import secrets

    out = []
    for r in conn.execute(
        "SELECT * FROM connector_accounts WHERE kind = 'clickup' AND state = 'active' ORDER BY id"
    ).fetchall():
        try:
            out.append(
                Account(r["id"], secrets.unseal(r["secret"])["token"], r["settings"]["team_id"])
            )
        except Exception:
            log.exception("cannot use ClickUp account %s", r["id"])
    return out


def refresh_lists(conn: Conn, client: ClickUpClient, account: Account) -> int:
    """Records the workspace's spaces/folders/lists (new ones are not synced until chosen)."""
    n = 0
    for space in client.spaces(account.team_id):
        found: list[tuple[str, dict[str, Any]]] = [
            (f.get("name", ""), lst)
            for f in client.folders(space["id"])
            for lst in f.get("lists") or []
        ]
        found += [("", lst) for lst in client.folderless_lists(space["id"])]
        for folder_name, lst in found:
            conn.execute(
                """
                INSERT INTO clickup_lists (list_id, account_id, space_id, space_name, folder_name,
                                           list_name)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (list_id) DO UPDATE SET space_name = EXCLUDED.space_name,
                    folder_name = EXCLUDED.folder_name, list_name = EXCLUDED.list_name,
                    seen_at = now()
                """,
                (
                    str(lst["id"]),
                    account.id,
                    str(space["id"]),
                    space.get("name", ""),
                    folder_name,
                    lst.get("name", ""),
                ),
            )
            n += 1
    return n


# --- sync ------------------------------------------------------------------------------------


def _ms(value: Any) -> datetime | None:
    return datetime.fromtimestamp(int(value) / 1000, UTC) if value else None


def source_id(account_id: int) -> str:
    return f"clickup-{account_id}"


def _person_keys(conn: Conn, users: list[dict[str, Any]]) -> list[str]:
    keys = []
    for u in users:
        email = (u.get("email") or "").lower()
        if email:
            key = people.email_key(email)
            people.register(conn, [key], u.get("username") or None)
            keys.append(key)
    return keys


def upsert_task(
    conn: Conn,
    account_id: int,
    task: dict[str, Any],
    comments: list[dict[str, Any]],
    scopes: list[str],
) -> int:
    sid = source_id(account_id)
    archive.put(
        conn,
        archive.RawRecord(
            source_id=sid,
            external_id=str(task["id"]),
            kind="clickup_task",
            occurred_at=_ms(task.get("date_updated")),
            payload={"task": task, "comments": comments},
        ),
    )
    assignees = list(task.get("assignees") or [])
    commenters = [c.get("user") or {} for c in comments]
    keys = list(
        dict.fromkeys(_person_keys(conn, assignees + commenters + [task.get("creator") or {}]))
    )
    status = task.get("status") or {}
    lines = [task.get("name") or "", task.get("text_content") or task.get("description") or ""]
    for c in comments:
        who = (c.get("user") or {}).get("username") or "?"
        lines.append(f"{who}: {c.get('comment_text') or ''}")
    meta = {
        "task_id": str(task["id"]),
        "list_id": str((task.get("list") or {}).get("id") or ""),
        "list": (task.get("list") or {}).get("name"),
        "status": status.get("status"),
        "status_type": status.get("type"),
        "due_date": due.isoformat() if (due := _ms(task.get("due_date"))) else None,
        "assignees": [a.get("username") for a in assignees],
        "assignee_emails": [(a.get("email") or "").lower() for a in assignees],
    }
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text, participants,
                           occurred_at, last_activity_at, locator, metadata, identity_keys)
        VALUES (%s, %s, 'clickup_task', %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, source_item_key) DO UPDATE SET scopes = EXCLUDED.scopes,
            title = EXCLUDED.title, raw_text = EXCLUDED.raw_text,
            participants = EXCLUDED.participants, last_activity_at = EXCLUDED.last_activity_at,
            locator = EXCLUDED.locator, metadata = EXCLUDED.metadata,
            identity_keys = EXCLUDED.identity_keys, hidden = false, updated_at = now()
        RETURNING id
        """,
        (
            sid,
            str(task["id"]),
            scopes or ["unsorted"],
            redact_text(task.get("name") or ""),
            redact_text("\n".join(lines)),
            [a.get("username") for a in assignees if a.get("username")],
            _ms(task.get("date_created")),
            _ms(task.get("date_updated")),
            task.get("url"),
            Jsonb(meta),
            keys,
        ),
    ).fetchone()
    assert row is not None
    if status.get("type") in CLOSED_TYPES:
        close_task_loops(conn, str(task["id"]))
    return int(row["id"])


def close_task_loops(conn: Conn, task_id: str) -> int:
    from kb import loops

    rows = conn.execute(
        "UPDATE loops SET status = 'done', closed_at = now() WHERE clickup_task_id = %s"
        " AND status IN ('open', 'snoozed') RETURNING id",
        (task_id,),
    ).fetchall()
    for r in rows:
        loops._event(conn, r["id"], "done", "system", via="clickup", task_id=task_id)
    return len(rows)


def sync_list(conn: Conn, client: ClickUpClient, account_id: int, list_row: dict[str, Any]) -> int:
    """Fetches tasks updated after the list's cursor; the cursor moves after every page, so an
    interruption (rate limit, crash) resumes without losing or repeating work."""
    synced, cursor = 0, int(list_row["cursor_ms"])
    for page in range(PAGE_LIMIT):
        tasks, last = client.tasks(list_row["list_id"], int(list_row["cursor_ms"]), page)
        for t in tasks:
            upsert_task(
                conn, account_id, t, client.comments(str(t["id"])), list(list_row["scopes"])
            )
            cursor = max(cursor, int(t.get("date_updated") or 0))
            synced += 1
        conn.execute(
            "UPDATE clickup_lists SET cursor_ms = %s WHERE list_id = %s",
            (cursor, list_row["list_id"]),
        )
        if last or not tasks:
            break
    return synced


def sync_account(conn: Conn, client: ClickUpClient, account: Account) -> int:
    rows = conn.execute(
        "SELECT * FROM clickup_lists WHERE account_id = %s AND sync ORDER BY list_id", (account.id,)
    ).fetchall()
    return sum(sync_list(conn, client, account.id, dict(r)) for r in rows)
