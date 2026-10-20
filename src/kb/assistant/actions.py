"""Action tools for requests (assistant-requests spec: drafts and tasks go to the approval queue,
loops changed directly with undo).

Drafts become suggestions with origin 'command' and the request id, so they appear inline in the
thread and in the queue; nothing here sends, saves to a mailbox or creates a task. Loop changes
apply at once and are recorded with their undo.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from psycopg.types.json import Jsonb

from kb import loops
from kb.assistant import suggestions
from kb.db import Conn

if TYPE_CHECKING:
    from kb.assistant.agent import Run

UNDO = {"add": "dismiss", "done": "reopen", "dismiss": "reopen", "snooze": "reopen"}


def _day(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def _now(run: Run) -> datetime:
    assert run.now is not None
    return run.now


def _item(conn: Conn, item_id: int, kind: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, kind, title, scopes, locator FROM items WHERE id = %s AND NOT hidden",
        (item_id,),
    ).fetchone()
    if row is None or row["kind"] != kind:
        raise ValueError(f"item {item_id} is not a {kind.replace('_', ' ')}")
    return dict(row)


def _drafted(run: Run, kind: str, sid: int, what: str) -> dict[str, Any]:
    run.step(kind, f"prepared {what} for your approval")
    run.record({"type": "suggestion", "id": sid, "kind": kind})
    return {"draft_id": sid, "status": "waiting for the owner's approval"}


def loops_tool(run: Run, person: str | None) -> Any:
    run.step("loops", "checked your open loops")
    rows = loops.list_loops(run.conn, _now(run), "open", person=person or None)
    return [
        {
            "loop_id": r["id"],
            "kind": r["kind"],
            "title": r["title"],
            "counterpart": r["counterpart"],
            "due_date": r["due_date"],
            "overdue": r["overdue"],
        }
        for r in rows[:30]
    ]


def draft_reply(run: Run, item_id: int, body: str) -> Any:
    item = _item(run.conn, item_id, "email_thread")
    sid = suggestions.propose(
        run.conn,
        "reply_email",
        {"item_id": item_id, "body": body.strip()},
        reason="From your request",
        refs=[f"item:{item_id}"],
        scopes=list(item["scopes"]),
        item_id=item_id,
        request_id=run.request_id,
    )
    run.seen.add(item_id)
    return _drafted(run, "draft_reply", sid, f"a reply to “{item['title'] or 'the email'}”")


def draft_email(run: Run, to: list[str], subject: str, body: str) -> Any:
    to = [a.strip() for a in to if "@" in a]
    if not to:
        raise ValueError("a new email needs a recipient address")
    sid = suggestions.propose(
        run.conn,
        "email",
        {"to": to, "subject": subject.strip(), "body": body.strip()},
        reason="From your request",
        request_id=run.request_id,
    )
    return _drafted(run, "draft_email", sid, f"an email to {', '.join(to)}")


def draft_tg_reply(run: Run, item_id: int, body: str) -> Any:
    item = _item(run.conn, item_id, "tg_conversation")
    link = item["locator"] if str(item["locator"] or "").startswith("https://") else None
    sid = suggestions.propose(
        run.conn,
        "reply_tg",
        {"item_id": item_id, "body": body.strip(), "channel": "telegram", "link": link},
        reason="From your request",
        refs=[f"item:{item_id}"],
        scopes=list(item["scopes"]),
        item_id=item_id,
        request_id=run.request_id,
    )
    run.seen.add(item_id)
    return _drafted(
        run, "draft_tg_reply", sid, f"a Telegram reply in “{item['title'] or 'the chat'}”"
    )


def resolve_assignee(conn: Conn, who: str) -> tuple[str, str] | None:
    """A teammate by name or email, from the assignees of synced ClickUp tasks."""
    who = who.strip().lower()
    if not who:
        return None
    seen: dict[str, str] = {}
    for r in conn.execute(
        "SELECT metadata->'assignees' AS names, metadata->'assignee_emails' AS emails"
        " FROM items WHERE kind = 'clickup_task' ORDER BY last_activity_at DESC NULLS LAST"
        " LIMIT 2000"
    ).fetchall():
        for name, email in zip(r["names"] or [], r["emails"] or [], strict=False):
            if email:
                seen.setdefault(email.lower(), name or email)
    for email, name in seen.items():
        n = name.lower()
        if who == email or (n and (who in n or n in who)):
            return name, email
    return None


def resolve_list(conn: Conn, name: str | None) -> tuple[str, str] | None:
    if name and name.strip():
        row = conn.execute(
            "SELECT list_id, list_name FROM clickup_lists WHERE sync AND list_name ILIKE %s"
            " ORDER BY length(list_name) LIMIT 1",
            (f"%{name.strip()}%",),
        ).fetchone()
        if row is not None:
            return str(row["list_id"]), str(row["list_name"])
    row = conn.execute(
        "SELECT list_id, list_name FROM clickup_lists WHERE default_for_drafts LIMIT 1"
    ).fetchone()
    return (str(row["list_id"]), str(row["list_name"])) if row else None


def draft_task(
    run: Run,
    name: str,
    description: str,
    assignee: str | None,
    list: str | None,
    due_date: str | None,
) -> Any:
    target = resolve_list(run.conn, list)
    if target is None:
        raise ValueError("no ClickUp list found: name one, or choose a default list for drafts")
    who = resolve_assignee(run.conn, assignee) if assignee else None
    _day(due_date)  # validates
    sid = suggestions.propose(
        run.conn,
        "task",
        {
            "list_id": target[0],
            "list": target[1],
            "name": name.strip(),
            "description": description.strip(),
            "assignee_emails": [who[1]] if who else [],
            "assignee_name": who[0] if who else (assignee or ""),
            "due_date": due_date,
        },
        reason="From your request",
        request_id=run.request_id,
    )
    for_whom = f" for {who[0]}" if who else ""
    result = _drafted(run, "draft_task", sid, f"a task “{name}”{for_whom} in {target[1]}")
    if assignee and who is None:
        result["note"] = f"no ClickUp teammate matches “{assignee}”; the owner can assign it"
    return result


def update_draft(
    run: Run,
    id: int,
    body: str | None,
    subject: str | None,
    name: str | None,
    assignee: str | None,
    due_date: str | None,
) -> Any:
    row = run.conn.execute(
        "SELECT s.id, s.kind, s.payload FROM suggestions s JOIN assistant_requests r"
        " ON r.id = s.request_id WHERE s.id = %s AND r.thread_id = %s AND s.status = 'proposed'",
        (id, run.thread_id),
    ).fetchone()
    if row is None:
        raise ValueError(f"draft {id} is not a pending draft from this conversation")
    changes: dict[str, Any] = {}
    if body is not None:
        changes["body"] = body.strip()
    if subject is not None:
        changes["subject"] = subject.strip()
    if name is not None:
        changes["name"] = name.strip()
    if due_date is not None:
        _day(due_date)
        changes["due_date"] = due_date
    if assignee is not None:
        who = resolve_assignee(run.conn, assignee)
        changes["assignee_emails"] = [who[1]] if who else []
        changes["assignee_name"] = who[0] if who else assignee
    run.conn.execute(
        "UPDATE suggestions SET payload = payload || %s WHERE id = %s", (Jsonb(changes), id)
    )
    run.step("update_draft", "updated the draft")
    return {"draft_id": id, "changed": sorted(changes)}


def add_reminder(run: Run, title: str, due_date: str | None, person: str | None) -> Any:
    lid = loops.add_manual(run.conn, title, _now(run), due=_day(due_date), counterpart=person or "")
    run.step(
        "add_reminder", f"added a reminder “{title}”" + (f" for {due_date}" if due_date else "")
    )
    run.record({"type": "loop", "id": lid, "action": "add", "title": title, "due": due_date})
    return {"loop_id": lid, "status": "added (the owner can undo)"}


def loop_action(run: Run, loop_id: int, action: str, until: str | None) -> Any:
    row = run.conn.execute("SELECT title FROM loops WHERE id = %s", (loop_id,)).fetchone()
    if row is None:
        raise ValueError(f"no loop {loop_id}")
    loops.act(run.conn, loop_id, action, _now(run), until=_day(until))  # type: ignore[arg-type]
    words = {"done": "closed", "dismiss": "dismissed", "snooze": "snoozed"}[action]
    run.step("loop_action", f"{words} “{row['title']}”")
    run.record({"type": "loop", "id": loop_id, "action": action, "title": row["title"]})
    return {"loop_id": loop_id, "status": f"{words} (the owner can undo)"}


def undo(conn: Conn, request_id: int, index: int, now: datetime) -> dict[str, Any]:
    """Reverses one loop change a request made."""
    row = conn.execute(
        "SELECT created FROM assistant_requests WHERE id = %s", (request_id,)
    ).fetchone()
    if row is None:
        raise ValueError(f"no request {request_id}")
    created = list(row["created"])
    if not 0 <= index < len(created) or created[index].get("type") != "loop":
        raise ValueError("nothing to undo there")
    entry = created[index]
    if entry.get("undone"):
        return entry
    loops.act(conn, int(entry["id"]), UNDO[entry["action"]], now, by="owner")  # type: ignore[arg-type]
    entry["undone"] = True
    conn.execute(
        "UPDATE assistant_requests SET created = %s WHERE id = %s", (Jsonb(created), request_id)
    )
    return entry


def activity(run: Run, date_from: str, date_to: str, scope: str | None) -> Any:
    from kb.routines import KYIV, factpack

    start = datetime.combine(date.fromisoformat(date_from), datetime.min.time(), tzinfo=KYIV)
    end = datetime.combine(date.fromisoformat(date_to), datetime.max.time(), tzinfo=KYIV)
    pack = factpack.build(run.conn, "weekly_review", (start, end))
    facts = [f for s, items in pack.by_scope.items() if not scope or s == scope for f in items]
    unique = list({f.id: f for f in facts}.values())[:80]
    for f in unique:
        run.seen.add(f.id)
    run.step(
        "activity",
        f"collected {len(unique)} items from {date_from} to {date_to}"
        + (f" in {scope}" if scope else ""),
    )
    open_loops = [lp for lp in loops.list_loops(run.conn, _now(run), "open", scope=scope or None)][
        :40
    ]
    return {
        "items": [
            {
                "id": f.ref,
                "kind": f.kind,
                "title": f.title,
                "summary": f.summary,
                "outcome": f.outcome,
                "date": f.last_activity_at.isoformat(),
                "scopes": f.scopes,
            }
            for f in unique
        ],
        "open_loops": [
            {
                "title": lp["title"],
                "kind": lp["kind"],
                "counterpart": lp["counterpart"],
                "due_date": lp["due_date"],
                "overdue": lp["overdue"],
            }
            for lp in open_loops
        ],
    }


def report(run: Run, title: str, sections: list[dict[str, Any]]) -> Any:
    allowed = {f"item:{i}" for i in run.seen}
    clean = []
    for s in sections:
        refs = [r for r in s.get("refs", []) if r in allowed]
        clean.append({"heading": s["heading"], "body": s["body"], "refs": refs})
    run.conn.execute(
        "UPDATE assistant_requests SET report = %s WHERE id = %s",
        (Jsonb({"title": title, "sections": clean}), run.request_id),
    )
    run.step("report", f"wrote the report “{title}”")
    return {"status": "report published", "sections": len(clean)}


def report_markdown(rep: dict[str, Any], titles: dict[str, str], origin: str = "") -> str:
    """The report as a Library note: sections with their sources as links."""
    out = [f"# {rep['title']}", ""]
    for s in rep["sections"]:
        out += [f"## {s['heading']}", "", s["body"], ""]
        if s["refs"]:
            links = [
                f"[{titles.get(r, r)}]({origin}/c/{r.removeprefix('item:')})" for r in s["refs"]
            ]
            out += ["Sources: " + ", ".join(links), ""]
    return "\n".join(out)


def draft_clickup_comment(run: Run, item_id: int, body: str, assign_to: str | None) -> Any:
    """A comment for a ClickUp task, waiting for the owner's approval; assigning it to a
    teammate notifies them in ClickUp."""
    item = _item(run.conn, item_id, "clickup_task")
    row = run.conn.execute(
        "SELECT source_id, source_item_key, locator FROM items WHERE id = %s", (item_id,)
    ).fetchone()
    assert row is not None
    assignee_id, assignee_name = None, ""
    if assign_to:
        settings = run.conn.execute(
            "SELECT settings FROM connector_accounts WHERE kind = 'clickup'"
            " AND 'clickup-' || id = %s",
            (row["source_id"],),
        ).fetchone()
        members = ((settings or {}).get("settings") or {}).get("members") or {}
        who = assign_to.strip().lower()
        for uid, m in members.items():
            name, email = (m.get("username") or "").lower(), (m.get("email") or "").lower()
            if who in (name, email) or (name and (who in name or name in who)):
                assignee_id, assignee_name = int(uid), m.get("username") or email
                break
    sid = suggestions.propose(
        run.conn,
        "clickup_comment",
        {
            "item_id": item_id,
            "task_id": row["source_item_key"],
            "link": row["locator"],
            "body": body.strip(),
            "assignee_id": assignee_id,
            "assignee_name": assignee_name,
        },
        reason="From your request",
        refs=[f"item:{item_id}"],
        scopes=list(item["scopes"]),
        item_id=item_id,
        request_id=run.request_id,
    )
    run.seen.add(item_id)
    result = _drafted(run, "draft_clickup_comment", sid, f"a comment on “{item['title']}”")
    if assign_to and assignee_id is None:
        result["note"] = f"no ClickUp member matches “{assign_to}”; the comment is not assigned"
    return result


HANDLERS: dict[str, Callable[..., Any]] = {
    "draft_clickup_comment": draft_clickup_comment,
    "activity": activity,
    "report": report,
    "loops": loops_tool,
    "draft_reply": draft_reply,
    "draft_email": draft_email,
    "draft_tg_reply": draft_tg_reply,
    "draft_task": draft_task,
    "update_draft": update_draft,
    "add_reminder": add_reminder,
    "loop_action": loop_action,
}
