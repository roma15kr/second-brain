"""ClickUp (clickup-integration spec, design D14).

Reads the owner's chosen lists with a personal API token: tasks changed since the list's cursor
(`date_updated_gt`) and their comments, every few minutes. A task with its comments is one
searchable item, marked by its list; assignees and commenters are linked to people by email.
Writes only one thing: a new task from a draft the owner approved. Respects the per-token rate
limit (429 → pause until the reset time, resume from the saved cursor).
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from psycopg.types.json import Jsonb

from kb import archive, distill, people
from kb.db import Conn
from kb.redact import redact_text

log = logging.getLogger(__name__)

API = "https://api.clickup.com/api/v2"
API3 = "https://api.clickup.com/api/v3"  # Chat (channels, messages)
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

    def create_comment(
        self,
        task_id: str,
        text: str,
        assignee: int | None = None,
        members: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """A comment on a task (approved by the owner); "@Name" of a workspace member becomes a
        real mention (a tag with their user id), and assigning the comment notifies that person."""
        parts = comment_parts(text, members or {}, assignee)
        body: dict[str, Any] = {"notify_all": False}
        if any(p.get("type") == "tag" for p in parts):
            body["comment"] = parts
        else:
            body["comment_text"] = text
        if assignee is not None:
            body["assignee"] = assignee
        return dict(self._req("POST", f"/task/{task_id}/comment", json=body))

    def team_members(self, team_id: str) -> dict[str, dict[str, Any]]:
        """user id → {username, email} for the workspace (chat messages carry only ids)."""
        for t in self.teams():
            if str(t["id"]) == str(team_id):
                return {
                    str((m.get("user") or {}).get("id")): {
                        "username": (m.get("user") or {}).get("username") or "",
                        "email": ((m.get("user") or {}).get("email") or "").lower(),
                    }
                    for m in t.get("members") or []
                }
        return {}

    def workspace_tasks(
        self, team_id: str, updated_gt_ms: int, page: int
    ) -> tuple[list[dict[str, Any]], bool]:
        """Tasks updated anywhere in the workspace (all lists the owner can see), newest first."""
        data = self._req(
            "GET",
            f"/team/{team_id}/task",
            params={
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

    def channels(self, team_id: str, since_ms: int | None = None) -> list[dict[str, Any]]:
        """Chat channels, DMs and group DMs visible to the owner (with messages since)."""
        params: dict[str, str] = {"limit": "100"}
        if since_ms:
            params["with_message_since"] = str(since_ms)
        return self._pages(f"{API3}/workspaces/{team_id}/chat/channels", params)

    def channel_member_ids(self, team_id: str, channel_id: str) -> set[str]:
        members = self._pages(
            f"{API3}/workspaces/{team_id}/chat/channels/{channel_id}/members", {"limit": "100"}
        )
        return {str(m.get("id") or (m.get("user") or {}).get("id")) for m in members}

    def _pages(self, path: str, params: dict[str, str], pages: int = 10) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for _ in range(pages):
            data = self._req("GET", path, params=params)
            out.extend(data.get("data") or [])
            if not data.get("next_cursor"):
                break
            params = {**params, "cursor": str(data["next_cursor"])}
        return out

    def followed_channels(self, team_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        params: dict[str, str] = {"is_follower": "true", "limit": "100"}
        for _ in range(10):
            data = self._req("GET", f"{API3}/workspaces/{team_id}/chat/channels", params=params)
            out.extend(data.get("data") or [])
            if not data.get("next_cursor"):
                break
            params = {**params, "cursor": str(data["next_cursor"])}
        return out

    def chat_messages(self, team_id: str, channel_id: str, since_ms: int) -> list[dict[str, Any]]:
        """Top-level messages newer than since_ms (the API returns newest first)."""
        out: list[dict[str, Any]] = []
        params: dict[str, str] = {"limit": "100", "content_format": "text/plain"}
        for _ in range(5):
            data = self._req(
                "GET",
                f"{API3}/workspaces/{team_id}/chat/channels/{channel_id}/messages",
                params=params,
            )
            page = list(data.get("data") or [])
            newer = [m for m in page if int(m.get("date") or 0) > since_ms]
            out.extend(newer)
            if len(newer) < len(page) or not data.get("next_cursor"):
                break
            params = {**params, "cursor": str(data["next_cursor"])}
        return sorted(out, key=lambda m: int(m.get("date") or 0))

    def groups(self, team_id: str) -> list[dict[str, Any]]:
        return list(self._req("GET", "/group", params={"team_id": team_id}).get("groups") or [])

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
    settings: dict[str, Any] | None = None


DEFAULT_GROUP = "DTC"


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


_MENTION = re.compile(r"@([^\s@,.;:!?]+)(?:\s([^\s@,.;:!?]+))?")


def comment_parts(
    text: str, members: dict[str, dict[str, Any]], assignee: int | None = None
) -> list[dict[str, Any]]:
    """ClickUp's rich comment: text pieces and `tag` mentions. "@Name" (full or first name of a
    member, unambiguous) becomes a tag; the assignee is tagged first when not mentioned."""
    by_name: dict[str, list[str]] = {}
    for member_id, member in members.items():
        name = (member.get("username") or "").strip().lower()
        if name:
            by_name.setdefault(name, []).append(member_id)
            by_name.setdefault(name.split()[0], []).append(member_id)

    def who(candidate: str) -> str | None:
        ids = set(by_name.get(candidate.lower(), []))
        return next(iter(ids)) if len(ids) == 1 else None

    parts: list[dict[str, Any]] = []
    tagged: set[str] = set()
    pos = 0
    for hit in _MENTION.finditer(text):
        uid: str | None = None
        end = hit.end(1)
        if hit.group(2):
            uid = who(f"{hit.group(1)} {hit.group(2)}")
            end = hit.end()
        if uid is None:
            uid, end = who(hit.group(1)), hit.end(1)
        if uid is None:
            continue
        if hit.start() > pos:
            parts.append({"text": text[pos : hit.start()]})
        parts.append({"type": "tag", "user": {"id": int(uid)}})
        tagged.add(uid)
        pos = end
    if pos < len(text):
        parts.append({"text": text[pos:]})
    if assignee is not None and str(assignee) not in tagged and str(assignee) in members:
        parts = [{"type": "tag", "user": {"id": int(assignee)}}, {"text": ", "}, *parts]
    return parts


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
    account: Account | None = None,
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
    if account is not None:
        detect_for_owner(conn, account, int(row["id"]), task, comments)
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
            conn,
            account.id,
            r["payload"]["task"],
            client.comments(r["task_id"]),
            list(r["scopes"]),
            account,
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
    account: Account | None = None,
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
                conn,
                account_id,
                t,
                client.comments(str(t["id"])),
                list(list_row["scopes"]),
                account,
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
        n, done = sync_list(conn, client, account.id, dict(r), deadline, account)
        total += n
        if not done:
            finished = False
            break
    return total, finished


# --- the owner's "inbox": tasks that involve them anywhere in the workspace ----------------------

INBOX_PAGES = 10  # up to 1,000 changed tasks per pass; the cursor moves only after a full walk


def _clock() -> float:
    """Time for the inbox walk's slices (tests replace it)."""
    import time

    return time.monotonic()


def involves_owner(task: dict[str, Any], settings: dict[str, Any]) -> bool:
    owner, group = settings.get("owner_user_id"), settings.get("group_id")
    if not owner:
        return False
    return (
        owner in _ids(task.get("assignees"))
        or owner in _ids(task.get("watchers"))
        or str((task.get("creator") or {}).get("id")) == owner
        or (bool(group) and group in _ids(task.get("group_assignees")))
    )


def sync_inbox(
    conn: Conn,
    client: ClickUpClient,
    account: Account,
    now: datetime,
    seconds: float | None = None,
) -> int:
    """ClickUp has no Inbox API, so the inbox is rebuilt: every task changed anywhere in the
    workspace (also in lists not chosen for sync) that the owner is assigned to, watches or
    created, or that is assigned to their team group, is stored with all comments and checked for
    mentions and assignments like synced tasks. Synced lists are left to their own walk."""
    from kb.connectors.base import get_state, set_state

    deadline = _clock() + seconds if seconds is not None else None
    sid = source_id(account.id)
    s = account.settings or {}
    if not s.get("owner_user_id"):
        return 0
    state = get_state(conn, sid, "inbox") or {}
    cursor = int(state.get("updated_ms") or int((now - timedelta(days=7)).timestamp() * 1000))
    lists = {
        str(r["list_id"]): r
        for r in conn.execute(
            "SELECT list_id, sync, scopes FROM clickup_lists WHERE account_id = %s", (account.id,)
        ).fetchall()
    }
    fallback = default_scopes(conn, account) or ["unsorted"]
    newest, stored = cursor, 0
    for page in range(INBOX_PAGES):
        tasks, last = client.workspace_tasks(account.team_id, cursor, page)
        for t in tasks:
            if deadline is not None and _clock() > deadline:
                return stored  # a time slice: the next pass skips what is already stored
            newest = max(newest, int(t.get("date_updated") or 0))
            row = lists.get(str((t.get("list") or {}).get("id")))
            if (row is not None and row["sync"]) or not involves_owner(t, s):
                continue
            if _unchanged(conn, account.id, t):
                continue
            scopes = list(row["scopes"]) if row is not None and row["scopes"] else fallback
            upsert_task(conn, account.id, t, client.comments(str(t["id"])), scopes, account)
            stored += 1
        if last:
            break
    set_state(conn, sid, "inbox", {"updated_ms": newest})
    return stored


# --- items for the owner (pushed right away) ---------------------------------------------------


def ensure_identity(
    conn: Conn, client: ClickUpClient, account: Account, now: datetime, refresh_group: bool = False
) -> dict[str, Any]:
    """The owner's ClickUp user id, the team group to watch (default DTC) and the moment
    notifications start (nothing older ever notifies)."""
    row = conn.execute(
        "SELECT settings FROM connector_accounts WHERE id = %s", (account.id,)
    ).fetchone()
    settings = {**(account.settings or {}), **(row["settings"] if row else {})}
    changed = False
    if not settings.get("owner_user_id"):
        user = client.user()
        settings["owner_user_id"] = str(user.get("id"))
        settings["owner_email"] = (user.get("email") or "").lower()
        changed = True
    if not settings.get("notify_since"):
        settings["notify_since"] = now.isoformat()
        changed = True
    if refresh_group or "group_id" not in settings:
        name = (settings.get("group_name") or DEFAULT_GROUP).lower()
        found = next(
            (g for g in client.groups(account.team_id) if (g.get("name") or "").lower() == name),
            None,
        )
        settings["group_id"] = str(found["id"]) if found else None
        changed = True
    if refresh_group or "members" not in settings:
        settings["members"] = client.team_members(account.team_id)
        changed = True
    if changed:
        conn.execute(
            "UPDATE connector_accounts SET settings = %s WHERE id = %s",
            (Jsonb(settings), account.id),
        )
        account.settings = settings
    return settings


def _ids(users: list[dict[str, Any]] | None) -> set[str]:
    return {str(u.get("id")) for u in users or [] if u.get("id") is not None}


def detect_for_owner(
    conn: Conn, account: Account, item_id: int, task: dict[str, Any], comments: list[dict[str, Any]]
) -> int:
    """Records events that concern the owner or the team group (each once)."""
    s = account.settings or {}
    owner, group = s.get("owner_user_id"), s.get("group_id")
    group_name = (s.get("group_name") or DEFAULT_GROUP).lower()
    since = datetime.fromisoformat(s["notify_since"]) if s.get("notify_since") else None
    if not owner or since is None:
        return 0
    events: list[tuple[str, str, str, datetime | None]] = []
    updated = _ms(task.get("date_updated"))
    followed = owner in _ids(task.get("watchers"))
    created = _ms(task.get("date_created"))
    creator = str((task.get("creator") or {}).get("id"))
    if followed and created and created > since and creator != owner:
        events.append((f"task:{task['id']}:new", "followed_new_task", "", created))
    if updated and updated > since:
        if owner in _ids(task.get("assignees")):
            events.append((f"task:{task['id']}:assigned:{owner}", "assigned", "", updated))
        if group and group in _ids(task.get("group_assignees")):
            events.append((f"task:{task['id']}:group:{group}", "group_assigned", "", updated))
    flat = [r for top in comments for r in [top, *(top.get("replies") or [])]]
    for c in flat:
        when = _ms(c.get("date"))
        author = c.get("user") or {}
        if when is None or when <= since or str(author.get("id")) == owner:
            continue
        actor = author.get("username") or ""
        cid = c.get("id")
        if str((c.get("assignee") or {}).get("id")) == owner:
            events.append((f"comment:{cid}:assigned", "comment_assigned", actor, when))
        parts = c.get("comment") or []
        mentions_owner = any(
            p.get("type") == "tag" and str((p.get("user") or {}).get("id")) == owner for p in parts
        )
        mentions_group = bool(group) and any(
            str((p.get("group") or p.get("user_group") or {}).get("id")) == group for p in parts
        )
        mentions_group = mentions_group or f"@{group_name}" in (c.get("comment_text") or "").lower()
        if group and str((c.get("group_assignee") or {}).get("id")) == group:
            mentions_group = True
        if mentions_owner:
            events.append((f"comment:{cid}:mentioned", "mentioned", actor, when))
        if mentions_group:
            events.append((f"comment:{cid}:group", "group_mentioned", actor, when))
        if followed and not (mentions_owner or mentions_group):
            events.append((f"comment:{cid}:followed", "followed_comment", actor, when))
    n = 0
    for key, kind, actor, when in events:
        row = conn.execute(
            "INSERT INTO clickup_notifications (key, account_id, item_id, kind, actor, event_at)"
            " VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING RETURNING key",
            (key, account.id, item_id, kind, actor, when),
        ).fetchone()
        n += 1 if row else 0
    return n


FOLLOWED = ("followed_new_task", "followed_comment", "followed_chat")
FOLLOWED_PUSH_EVERY = timedelta(
    minutes=15
)  # followed activity: one summary push at most this often

HEADLINES = {
    "followed_new_task": "ClickUp: new task you follow",
    "followed_comment": "ClickUp: {actor} commented on a task you follow",
    "followed_chat": "ClickUp chat: {actor} wrote in a channel you follow",
    "assigned": "ClickUp: a task was assigned to you",
    "group_assigned": "ClickUp: a task was assigned to {group}",
    "mentioned": "ClickUp: {actor} mentioned you",
    "group_mentioned": "ClickUp: {actor} mentioned {group}",
    "comment_assigned": "ClickUp: {actor} assigned you a comment",
    "chat_direct": "ClickUp: {actor} wrote to you",
}


def push_pending(conn: Conn, now: datetime) -> int:
    """Routines service. Items for the owner (assigned, mentioned) push one by one; followed
    activity is summed up in one push at most every 15 minutes. During quiet hours nothing is
    pushed: the items are held for the next brief instead (no late-night buzz, no duplicate)."""
    from kb import loops, push, settings_store

    quiet = settings_store.load(conn).quiet_hours
    pending = conn.execute(
        "SELECT n.*, a.settings FROM clickup_notifications n"
        " JOIN connector_accounts a ON a.id = n.account_id"
        " WHERE n.handled_at IS NULL ORDER BY n.created_at"
    ).fetchall()
    if not pending:
        return 0
    if push.in_quiet_hours(now, quiet.start, quiet.end):
        conn.execute(
            "UPDATE clickup_notifications SET handled_at = %s WHERE key = ANY(%s)",
            (now, [r["key"] for r in pending]),
        )
        return 0
    sent = 0
    for r in [r for r in pending if r["kind"] not in FOLLOWED][:20]:
        group = (r["settings"] or {}).get("group_name") or DEFAULT_GROUP
        headline = HEADLINES[r["kind"]].format(actor=r["actor"] or "Someone", group=group)
        url = f"/c/{r['item_id']}" if r["item_id"] else "/clickup"
        n = push.send(conn, "clickup", headline, url, now)
        conn.execute(
            "UPDATE clickup_notifications SET handled_at = %s, pushed = %s WHERE key = %s",
            (now, n > 0, r["key"]),
        )
        sent += n
    followed = [r for r in pending if r["kind"] in FOLLOWED]
    last = loops.get_setting(conn, "clickup_followed_pushed_at", None)
    if followed and (last is None or now - datetime.fromisoformat(last) >= FOLLOWED_PUSH_EVERY):
        items = {r["item_id"] for r in followed}
        chats = sum(1 for r in followed if r["kind"] == "followed_chat")
        parts = [
            f"{len(followed) - chats} task updates" if len(followed) > chats else "",
            f"{chats} chat messages" if chats else "",
        ]
        headline = "ClickUp: " + " and ".join(p for p in parts if p) + " you follow"
        url = f"/c/{next(iter(items))}" if len(items) == 1 and None not in items else "/clickup"
        n = push.send(conn, "clickup", headline, url, now)
        conn.execute(
            "UPDATE clickup_notifications SET handled_at = %s, pushed = %s WHERE key = ANY(%s)",
            (now, n > 0, [r["key"] for r in followed]),
        )
        loops.set_setting(conn, "clickup_followed_pushed_at", now.isoformat())
        sent += n
    return sent


# --- chat channels the owner follows ------------------------------------------------------------


def default_scopes(conn: Conn, account: Account) -> list[str] | None:
    """The workspace's own mark (Connectors → ClickUp), for lists without one and chat."""
    row = conn.execute(
        "SELECT settings->>'default_scope' AS s FROM connector_accounts WHERE id = %s",
        (account.id,),
    ).fetchone()
    return [row["s"]] if row and row["s"] else None


def chat_scopes(conn: Conn, account_id: int) -> list[str]:
    """Chat is marked with the workspace mark, else like most of the account's synced lists."""
    row = conn.execute(
        "SELECT settings->>'default_scope' AS s FROM connector_accounts WHERE id = %s",
        (account_id,),
    ).fetchone()
    if row and row["s"]:
        return [row["s"]]
    row = conn.execute(
        "SELECT s, count(*) AS n FROM clickup_lists, unnest(scopes) s WHERE account_id = %s"
        " AND sync GROUP BY s ORDER BY n DESC LIMIT 1",
        (account_id,),
    ).fetchone()
    return [row["s"]] if row else ["unsorted"]


MEMBERS_TTL = timedelta(hours=24)


def my_channels(
    conn: Conn, client: ClickUpClient, account: Account, since_ms: int, now: datetime
) -> list[dict[str, Any]]:
    """Direct messages, group DMs, and channels the owner follows or is a member of (membership
    is checked per channel and remembered for a day)."""
    from kb.connectors.base import get_state, set_state

    sid = source_id(account.id)
    owner = str((account.settings or {}).get("owner_user_id") or "")
    followed = {str(c["id"]) for c in client.followed_channels(account.team_id)}
    out = []
    for ch in client.channels(account.team_id, since_ms):
        cid = str(ch["id"])
        if ch.get("type") in ("DM", "GROUP_DM") or cid in followed:
            out.append(ch)
            continue
        cached = get_state(conn, sid, f"chatmember:{cid}") or {}
        checked = cached.get("checked")
        if checked and now - datetime.fromisoformat(checked) < MEMBERS_TTL:
            member = bool(cached.get("member"))
        else:
            member = owner in client.channel_member_ids(account.team_id, cid)
            set_state(
                conn, sid, f"chatmember:{cid}", {"member": member, "checked": now.isoformat()}
            )
        if member:
            out.append(ch)
    return out


def _chat_kind(ch: dict[str, Any], text: str, owner_name: str, group_name: str) -> str:
    if ch.get("type") in ("DM", "GROUP_DM"):
        return "chat_direct"
    low = text.lower()
    if owner_name and f"@{owner_name.lower()}" in low:
        return "mentioned"
    if group_name and f"@{group_name.lower()}" in low:
        return "group_mentioned"
    return "followed_chat"


def sync_chat(conn: Conn, client: ClickUpClient, account: Account, now: datetime) -> int:
    """New messages in the owner's DMs and channels: archived, indexed per channel per day
    (searchable), and noted for the owner when written by someone else — DMs and @mentions push
    right away, the rest is summed up."""
    from kb.connectors.base import get_state, set_state

    sid = source_id(account.id)
    s = account.settings or {}
    members: dict[str, dict[str, Any]] = s.get("members") or {}
    owner = str(s.get("owner_user_id") or "")
    owner_name = (members.get(owner) or {}).get("username") or ""
    group_name = s.get("group_name") or DEFAULT_GROUP
    since_notify = datetime.fromisoformat(s["notify_since"]) if s.get("notify_since") else now
    scopes = chat_scopes(conn, account.id)
    listed = get_state(conn, sid, "chat:listed") or {}
    list_since = int(listed.get("since_ms") or int((now - timedelta(days=30)).timestamp() * 1000))
    stored = 0
    for ch in my_channels(conn, client, account, list_since - 60_000, now):
        cid = str(ch["id"])
        state = get_state(conn, sid, f"chat:{cid}") or {}
        since_ms = int(state.get("since_ms") or int((now - timedelta(days=30)).timestamp() * 1000))
        messages = client.chat_messages(account.team_id, cid, since_ms)
        days: set[str] = set()
        for m in messages:
            archive.put(
                conn,
                archive.RawRecord(
                    source_id=sid,
                    external_id=f"chat:{m['id']}",
                    kind="clickup_chat_message",
                    occurred_at=_ms(m.get("date")),
                    payload={
                        "channel": {"id": cid, "name": ch.get("name"), "type": ch.get("type")},
                        "message": m,
                    },
                ),
            )
            when = _ms(m.get("date"))
            if when is None:
                continue
            days.add(when.date().isoformat())
            since_ms = max(since_ms, int(m.get("date") or 0))
            stored += 1
        item_ids = {d: _index_chat_day(conn, sid, ch, d, members, scopes) for d in sorted(days)}
        for m in messages:
            when = _ms(m.get("date"))
            author = str(m.get("user_id") or "")
            if when is None or when <= since_notify or author == owner:
                continue
            kind = _chat_kind(ch, str(m.get("content") or ""), owner_name, group_name)
            conn.execute(
                "INSERT INTO clickup_notifications (key, account_id, item_id, kind, actor,"
                " event_at) VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING",
                (
                    f"chat:{m['id']}",
                    account.id,
                    item_ids.get(when.date().isoformat()),
                    kind,
                    (members.get(author) or {}).get("username") or "",
                    when,
                ),
            )
        set_state(conn, sid, f"chat:{cid}", {"since_ms": since_ms})
    set_state(conn, sid, "chat:listed", {"since_ms": int(now.timestamp() * 1000)})
    return stored


def _index_chat_day(
    conn: Conn,
    sid: str,
    channel: dict[str, Any],
    day: str,
    members: dict[str, dict[str, Any]],
    scopes: list[str],
) -> int:
    rows = conn.execute(
        "SELECT payload FROM raw_records WHERE source_id = %s AND kind = 'clickup_chat_message'"
        " AND payload->'channel'->>'id' = %s"
        " AND (to_timestamp((payload->'message'->>'date')::bigint / 1000.0) AT TIME ZONE 'UTC')"
        "::date = %s::date",
        (sid, str(channel["id"]), day),
    ).fetchall()
    msgs = sorted((r["payload"]["message"] for r in rows), key=lambda m: int(m.get("date") or 0))
    seen: set[str] = set()
    lines, keys, people_ = [], [], []
    for m in msgs:
        if m["id"] in seen:
            continue
        seen.add(m["id"])
        user = members.get(str(m.get("user_id"))) or {}
        who = user.get("username") or "?"
        lines.append(f"{who}: {m.get('content') or ''}")
        if user.get("email"):
            keys.append(people.email_key(user["email"]))
            people_.append(who)
    last = _ms(msgs[-1].get("date")) if msgs else None
    text = redact_text("\n".join(lines))
    if channel.get("type") in ("DM", "GROUP_DM"):
        others = sorted({p for p in people_ if p} - {""})
        title = f"DM {', '.join(others) or channel.get('name') or ''} · {day}".replace("  ", " ")
    else:
        title = f"#{channel.get('name') or 'chat'} · {day}"
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text, participants,
                           occurred_at, last_activity_at, identity_keys, metadata, content_hash)
        VALUES (%s, %s, 'clickup_chat', %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (source_id, source_item_key) DO UPDATE SET raw_text = EXCLUDED.raw_text,
            participants = EXCLUDED.participants, last_activity_at = EXCLUDED.last_activity_at,
            identity_keys = EXCLUDED.identity_keys, content_hash = EXCLUDED.content_hash,
            updated_at = now()
        RETURNING id
        """,
        (
            sid,
            f"chat:{channel['id']}:{day}",
            scopes,
            title,
            text,
            sorted(set(people_)),
            _ms(msgs[0].get("date")) if msgs else None,
            last,
            sorted(set(keys)),
            Jsonb({"channel_id": str(channel["id"]), "channel": channel.get("name"), "day": day}),
            distill.content_hash(title, text),
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def for_brief(conn: Conn, window: tuple[datetime, datetime]) -> list[dict[str, Any]]:
    """ClickUp items for the owner in a brief's window, one row per task."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (n.item_id) n.item_id, n.kind, n.actor, n.created_at, i.title,
               i.locator, i.scopes, a.settings
        FROM clickup_notifications n JOIN items i ON i.id = n.item_id
        JOIN connector_accounts a ON a.id = n.account_id
        WHERE n.created_at > %s AND n.created_at <= %s
        ORDER BY n.item_id, n.created_at DESC
        """,
        window,
    ).fetchall()
    out = []
    for r in rows:
        group = (r["settings"] or {}).get("group_name") or DEFAULT_GROUP
        why = HEADLINES[r["kind"]].format(actor=r["actor"] or "Someone", group=group)
        out.append(
            {
                "ref": f"item:{r['item_id']}",
                "id": r["item_id"],
                "kind": "clickup_task",
                "title": r["title"],
                "summary": why.removeprefix("ClickUp: "),
                "outcome": None,
                "link": r["locator"],
                "last_activity_at": r["created_at"].isoformat(),
                "scopes": list(r["scopes"]),
                "participants": [r["actor"]] if r["actor"] else [],
            }
        )
    return out
