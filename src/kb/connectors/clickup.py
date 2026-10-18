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

from kb import archive, distill, people
from kb.db import Conn
from kb.redact import redact_text

log = logging.getLogger(__name__)

API = "https://api.clickup.com/api/v2"
PAGE_SIZE = 100  # ClickUp returns up to 100 tasks per page
PAGE_LIMIT = 50  # safety bound on pages per list per walk
MIN_INTERVAL = 0.65  # seconds between requests: stays under 100 requests/minute
COMMENTS_PER_PAGE = 25  # ClickUp returns the 25 newest comments per request
COMMENT_PAGES = 40  # up to 1,000 comments per task
SECTION_CHARS = 1500  # long comment threads are also indexed in chunks
RECENT_DAYS = 30  # open tasks active this recently are checked for new comments
CLOSED_TYPES = {"closed", "done"}


_REVERSE_FOR_NEWEST: dict[str, bool] = {}


class ClickUpError(RuntimeError):
    pass


class RateLimited(ClickUpError):
    def __init__(self, reset_at: float) -> None:
        super().__init__(f"ClickUp rate limit reached; resets at {reset_at:.0f}")
        self.reset_at = reset_at


class ClickUpClient:
    def __init__(
        self,
        token: str,
        transport: httpx.BaseTransport | None = None,
        min_interval: float | None = None,
    ) -> None:
        self.http = httpx.Client(
            base_url=API, headers={"Authorization": token}, timeout=30, transport=transport
        )
        # a fake transport (tests) needs no throttling
        self.min_interval = (
            (0.0 if transport else MIN_INTERVAL) if min_interval is None else min_interval
        )
        self._last = 0.0
        # Whether ClickUp needs reverse=true to return the newest tasks first (not documented;
        # detected from the first page that has two tasks with different update times).
        self.reverse_for_newest: bool = _REVERSE_FOR_NEWEST.get("value", False)

    def _req(self, method: str, path: str, **kw: Any) -> Any:
        import time

        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
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
                **({"reverse": "true"} if self.reverse_for_newest else {}),
                "date_updated_gt": str(updated_gt_ms),
                "page": str(page),
            },
        )
        tasks = list(data.get("tasks") or [])
        last = data.get("last_page")
        return tasks, bool(last) if last is not None else len(tasks) < PAGE_SIZE

    def comments(self, task_id: str) -> list[dict[str, Any]]:
        """Every comment of a task, oldest first, with threaded replies under `replies`.
        ClickUp returns the 25 newest per request; older pages via start/start_id."""
        out: list[dict[str, Any]] = []
        params: dict[str, str] = {}
        for _ in range(COMMENT_PAGES):
            page = list(
                self._req("GET", f"/task/{task_id}/comment", params=params).get("comments") or []
            )
            out.extend(c for c in page if all(c.get("id") != o.get("id") for o in out[-25:]))
            if len(page) < COMMENTS_PER_PAGE:
                break
            last = page[-1]
            params = {"start": str(last.get("date")), "start_id": str(last.get("id"))}
        for c in out:
            if int(c.get("reply_count") or 0) > 0:
                c["replies"] = list(
                    self._req("GET", f"/comment/{c['id']}/reply").get("comments") or []
                )
        return sorted(out, key=lambda c: int(c.get("date") or 0))

    def newest_comment_id(self, task_id: str) -> str | None:
        page = self._req("GET", f"/task/{task_id}/comment").get("comments") or []
        return str(page[0]["id"]) if page else None

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
    flat = [r for c in comments for r in [c, *(c.get("replies") or [])]]
    commenters = [c.get("user") or {} for c in flat]
    keys = list(
        dict.fromkeys(_person_keys(conn, assignees + commenters + [task.get("creator") or {}]))
    )
    status = task.get("status") or {}
    header = [task.get("name") or "", task.get("text_content") or task.get("description") or ""]
    comment_lines = []
    for c in comments:  # oldest first: summaries read the newest end of long texts
        comment_lines.append(_comment_line(c))
        comment_lines += ["  ↳ " + _comment_line(r) for r in c.get("replies") or []]
    lines = header + comment_lines
    title = redact_text(task.get("name") or "")
    text = redact_text("\n".join(lines))
    newest_comment = _ms(comments[-1].get("date")) if comments else None
    updated = _ms(task.get("date_updated"))
    last_activity = max((d for d in (updated, newest_comment) if d), default=None)
    meta = {
        "task_id": str(task["id"]),
        "date_updated": str(task.get("date_updated") or ""),
        "list_id": str((task.get("list") or {}).get("id") or ""),
        "list": (task.get("list") or {}).get("name"),
        "status": status.get("status"),
        "status_type": status.get("type"),
        "due_date": due.isoformat() if (due := _ms(task.get("due_date"))) else None,
        "assignees": [a.get("username") for a in assignees],
        "assignee_emails": [(a.get("email") or "").lower() for a in assignees],
        "comments": len(flat),
        "newest_comment_id": str(comments[-1].get("id")) if comments else None,
    }
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text, participants,
                           occurred_at, last_activity_at, locator, metadata, identity_keys,
                           content_hash)
        VALUES (%s, %s, 'clickup_task', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, source_item_key) DO UPDATE SET scopes = EXCLUDED.scopes,
            title = EXCLUDED.title, raw_text = EXCLUDED.raw_text,
            content_hash = EXCLUDED.content_hash,
            participants = EXCLUDED.participants, last_activity_at = EXCLUDED.last_activity_at,
            locator = EXCLUDED.locator, metadata = EXCLUDED.metadata,
            identity_keys = EXCLUDED.identity_keys, hidden = false, updated_at = now()
        RETURNING id
        """,
        (
            sid,
            str(task["id"]),
            scopes or ["unsorted"],
            title,
            text,
            [a.get("username") for a in assignees if a.get("username")],
            _ms(task.get("date_created")),
            last_activity,
            task.get("url"),
            Jsonb(meta),
            keys,
            distill.content_hash(title, text),
        ),
    ).fetchone()
    assert row is not None
    _index_comment_chunks(
        conn, sid, str(task["id"]), int(row["id"]), title, comment_lines, scopes, last_activity
    )
    if status.get("type") in CLOSED_TYPES:
        close_task_loops(conn, str(task["id"]))
    return int(row["id"])


def _comment_line(c: dict[str, Any]) -> str:
    who = (c.get("user") or {}).get("username") or "?"
    when = _ms(c.get("date"))
    stamp = when.strftime("%Y-%m-%d") if when else ""
    return f"[{stamp}] {who}: {c.get('comment_text') or ''}"


def _index_comment_chunks(
    conn: Conn,
    sid: str,
    task_id: str,
    parent_id: int,
    title: str,
    lines: list[str],
    scopes: list[str],
    last_activity: datetime | None,
) -> None:
    """Long discussions are also indexed in chunks (newest last), so a detail deep in the
    comments is found and reported as its task."""
    conn.execute(
        "DELETE FROM items WHERE source_id = %s AND source_item_key LIKE %s",
        (sid, f"{task_id}#c%"),
    )
    if sum(len(x) for x in lines) < SECTION_CHARS:
        return
    chunks, buf = [], ""
    for line in lines:
        if buf and len(buf) + len(line) > SECTION_CHARS:
            chunks.append(buf)
            buf = ""
        buf += line + "\n"
    if buf:
        chunks.append(buf)
    for n, chunk in enumerate(chunks):
        conn.execute(
            "INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text,"
            " last_activity_at, metadata) VALUES (%s, %s, 'clickup_comments', %s, %s, %s, %s, %s)",
            (
                sid,
                f"{task_id}#c{n}",
                scopes or ["unsorted"],
                f"{title} - comments",
                redact_text(chunk),
                last_activity,
                Jsonb({"parent_item_id": parent_id, "task_id": task_id}),
            ),
        )


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


def _oldest_first(tasks: list[dict[str, Any]]) -> bool:
    times = [int(t.get("date_updated") or 0) for t in tasks]
    return len(set(times)) > 1 and times[0] < times[-1]


def refresh_recent_comments(
    conn: Conn, client: ClickUpClient, account: Account, limit: int = 60
) -> int:
    """New comments may not change a task's update time, so open tasks active in the last
    RECENT_DAYS are checked for a newer comment (one request each) and re-read when found."""
    sid = source_id(account.id)
    rows = conn.execute(
        """
        SELECT i.source_item_key AS task_id, i.metadata->>'newest_comment_id' AS newest,
               i.scopes,
               (SELECT r.payload FROM raw_records r WHERE r.source_id = i.source_id
                  AND r.external_id = i.source_item_key ORDER BY r.id DESC LIMIT 1) AS payload
        FROM items i
        WHERE i.source_id = %s AND i.kind = 'clickup_task' AND NOT i.hidden
          AND coalesce(i.metadata->>'status_type', '') NOT IN ('closed', 'done')
          AND i.last_activity_at > now() - make_interval(days => %s)
        ORDER BY i.last_activity_at DESC LIMIT %s
        """,
        (sid, RECENT_DAYS, limit),
    ).fetchall()
    updated = 0
    for r in rows:
        if r["payload"] is None:
            continue
        if client.newest_comment_id(r["task_id"]) == r["newest"]:
            continue
        upsert_task(
            conn, account.id, r["payload"]["task"], client.comments(r["task_id"]), list(r["scopes"])
        )
        updated += 1
    return updated


def _unchanged(conn: Conn, account_id: int, task: dict[str, Any]) -> bool:
    row = conn.execute(
        "SELECT metadata->>'date_updated' AS u FROM items WHERE source_id = %s"
        " AND source_item_key = %s",
        (source_id(account_id), str(task["id"])),
    ).fetchone()
    return row is not None and row["u"] == str(task.get("date_updated") or "")


def sync_list(
    conn: Conn,
    client: ClickUpClient,
    account_id: int,
    list_row: dict[str, Any],
    deadline: float | None = None,
) -> tuple[int, bool]:
    """Walks every page of tasks updated after the list's cursor. Tasks already stored unchanged
    are skipped without further requests, so a walk interrupted by the rate limit resumes almost
    for free; the cursor moves only after the last page, which makes the walk correct whatever
    order ClickUp returns tasks in. Returns (tasks stored, walk finished); past `deadline`
    (time.monotonic) it stops early and the next call continues cheaply."""
    import time

    synced, newest = 0, int(list_row["cursor_ms"])
    for page in range(PAGE_LIMIT):
        tasks, last = client.tasks(list_row["list_id"], int(list_row["cursor_ms"]), page)
        if page == 0 and _oldest_first(tasks):  # the owner wants the newest work first
            client.reverse_for_newest = not client.reverse_for_newest
            _REVERSE_FOR_NEWEST["value"] = client.reverse_for_newest
            tasks, last = client.tasks(list_row["list_id"], int(list_row["cursor_ms"]), page)
        for t in tasks:
            newest = max(newest, int(t.get("date_updated") or 0))
            if _unchanged(conn, account_id, t):
                continue
            if deadline is not None and time.monotonic() > deadline:
                return synced, False
            upsert_task(
                conn, account_id, t, client.comments(str(t["id"])), list(list_row["scopes"])
            )
            synced += 1
        if last or not tasks:
            conn.execute(
                "UPDATE clickup_lists SET cursor_ms = %s WHERE list_id = %s",
                (newest, list_row["list_id"]),
            )
            return synced, True
    return synced, False


def sync_account(
    conn: Conn, client: ClickUpClient, account: Account, seconds: float | None = None
) -> int:
    """Syncs every chosen list (all of it, or for about `seconds`: see sync_account_for)."""
    return sync_account_for(conn, client, account, seconds)[0]


def sync_account_for(
    conn: Conn, client: ClickUpClient, account: Account, seconds: float | None
) -> tuple[int, bool]:
    import time

    deadline = time.monotonic() + seconds if seconds is not None else None
    rows = conn.execute(
        "SELECT * FROM clickup_lists WHERE account_id = %s AND sync ORDER BY list_id", (account.id,)
    ).fetchall()
    total, finished = 0, True
    for r in rows:
        n, done = sync_list(conn, client, account.id, dict(r), deadline)
        total += n
        if not done:
            finished = False
            break
    return total, finished
