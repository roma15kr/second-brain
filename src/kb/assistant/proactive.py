"""Nudges, delegation suggestions and learning from discards (assistant-actions spec: two-minute
items and nudges, delegation suggestions, learning from corrections; web-os-v1 task 12.5).

- Nudge: a promise owed to the owner is overdue → a short, polite follow-up draft in the
  conversation's language (email: saved to Drafts or sent on tap; Telegram: copied by the owner).
- Delegate: a new email that needs the owner looks like work a teammate already does (its meaning
  matches ClickUp tasks mostly assigned to one person) → a ClickUp task draft for that person.
- Learning: when the owner discarded the last five decisions of a kind, that kind is proposed at
  most once a day; Status shows the acceptance rate per kind.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from kb import distill, loops, settings_store
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm

log = logging.getLogger(__name__)

AI_SOURCE = "assistant"
NUDGE_AGAIN_DAYS = 3
COOLING_STREAK = 5  # discards in a row that slow a kind down
SIMILAR_TASKS, TASK_SIMILARITY, MIN_SHARE = 10, 0.84, 3

NUDGE_SYSTEM = """Write a short, polite follow-up (2-4 sentences) from the owner reminding the other
person of what they promised. Use the language of the conversation (Ukrainian, Russian or
English), be friendly, no pressure, no invented details. Body only, no subject."""
NUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"body": {"type": "string"}},
    "required": ["body"],
    "additionalProperties": False,
}


# --- learning from discards -------------------------------------------------------------------


def cooling(conn: Conn, kind: str) -> bool:
    rows = conn.execute(
        "SELECT status FROM suggestions WHERE kind = %s AND decided_at IS NOT NULL"
        " ORDER BY decided_at DESC LIMIT %s",
        (kind, COOLING_STREAK),
    ).fetchall()
    return len(rows) == COOLING_STREAK and all(r["status"] == "discarded" for r in rows)


def allowed(conn: Conn, kind: str, now: datetime) -> bool:
    """A cooling kind is proposed at most once a day; others whenever there is reason."""
    if not cooling(conn, kind):
        return True
    row = conn.execute(  # created_at is stamped by the database clock
        "SELECT 1 FROM suggestions WHERE kind = %s AND created_at > now() - interval '1 day'"
        " LIMIT 1",
        (kind,),
    ).fetchone()
    return row is None


def acceptance(conn: Conn, now: datetime, days: int = 28) -> list[dict[str, Any]]:
    """Per kind: approved (as is or edited) vs discarded in the window."""
    rows = conn.execute(
        """
        SELECT kind,
               count(*) FILTER (WHERE status IN ('approved', 'applying', 'applied')) AS accepted,
               count(*) FILTER (WHERE status IN ('approved', 'applying', 'applied') AND edited)
                   AS edited,
               count(*) FILTER (WHERE status = 'discarded') AS discarded
        FROM suggestions WHERE decided_at > %s GROUP BY kind ORDER BY kind
        """,
        (now - timedelta(days=days),),
    ).fetchall()
    out = []
    for r in rows:
        decided = r["accepted"] + r["discarded"]
        out.append(
            {
                "kind": r["kind"],
                "accepted": r["accepted"],
                "edited": r["edited"],
                "discarded": r["discarded"],
                "rate": round(r["accepted"] / decided, 2) if decided else None,
                "cooling": cooling(conn, r["kind"]),
            }
        )
    return out


def assistant_metric(conn: Conn, now: datetime) -> dict[str, Any]:
    """assistant-command-v1 success metric: requests per week, and the share of drafts and tasks
    made from requests that were approved (target: 15 a week, 60%)."""
    week = conn.execute(
        "SELECT count(*) AS n FROM assistant_requests WHERE started_at > %s",
        (now - timedelta(days=7),),
    ).fetchone()
    by_origin = conn.execute(
        """
        SELECT origin,
               count(*) FILTER (WHERE status IN ('approved', 'applying', 'applied')) AS accepted,
               count(*) FILTER (WHERE status = 'discarded') AS discarded
        FROM suggestions WHERE decided_at > %s GROUP BY origin
        """,
        (now - timedelta(days=28),),
    ).fetchall()
    rates = {}
    for r in by_origin:
        decided = r["accepted"] + r["discarded"]
        rates[r["origin"]] = round(r["accepted"] / decided, 2) if decided else None
    return {
        "requests_7d": int(week["n"]) if week else 0,
        "requests_target": 15,
        "approved_from_requests": rates.get("command"),
        "approved_from_routines": rates.get("routine"),
        "approved_target": 0.6,
    }


# --- nudges -----------------------------------------------------------------------------------


def nudge_candidates(conn: Conn, now: datetime, limit: int = 1) -> list[dict[str, Any]]:
    today = loops.kyiv_today(now)
    return [
        dict(r)
        for r in conn.execute(
            """
            SELECT l.id, l.title, l.counterpart, l.due_date, l.item_id, l.scopes, l.source_link,
                   i.kind AS item_kind, i.language, i.source_id, i.source_item_key
            FROM loops l JOIN items i ON i.id = l.item_id
            WHERE l.kind = 'owed_to_me' AND l.status = 'open' AND l.due_date < %s
              AND l.clickup_task_id IS NULL
              AND i.kind IN ('email_thread', 'tg_conversation')
              AND NOT EXISTS (SELECT 1 FROM suggestions s WHERE s.kind = 'nudge'
                              AND (s.payload->>'loop_id')::bigint = l.id
                              AND (s.status = 'proposed' OR s.created_at > %s))
            ORDER BY l.due_date LIMIT %s
            """,
            (today, now - timedelta(days=NUDGE_AGAIN_DAYS), limit),
        ).fetchall()
    ]


def _nudge_text(conn: Conn, loop: dict[str, Any], today: Any) -> str:
    msgs = conn.execute(
        "SELECT author, body FROM messages WHERE source_id = %s AND unit_key = %s AND NOT hidden"
        " ORDER BY sent_at DESC LIMIT 4",
        (loop["source_id"], loop["source_item_key"]),
    ).fetchall()
    convo = "\n".join(f"{m['author']}: {m['body'][-500:]}" for m in reversed(msgs))
    days = (today - loop["due_date"]).days
    return (
        f"PROMISE: {loop['title']} (by {loop['counterpart']}, due {loop['due_date']}, "
        f"{days} days overdue)\nLANGUAGE: {loop['language'] or 'as in the conversation'}\n"
        f"CONVERSATION (latest):\n{convo}"
    )


def nudges(conn: Conn, config: Config, llm: StructuredLlm, now: datetime) -> int:
    from kb.assistant import suggestions

    if not allowed(conn, "nudge", now):
        return 0
    today = loops.kyiv_today(now)
    done = 0
    for lp in nudge_candidates(conn, now):
        model = config.llm.model()
        data, usage = llm.structured(
            model, NUDGE_SYSTEM, _nudge_text(conn, lp, today), NUDGE_SCHEMA, "nudge", "low"
        )
        distill.record_usage(conn, AI_SOURCE, model, "nudge", usage)
        days = (today - lp["due_date"]).days
        suggestions.propose(
            conn,
            "nudge",
            {
                "loop_id": lp["id"],
                "item_id": lp["item_id"],
                "channel": "email" if lp["item_kind"] == "email_thread" else "telegram",
                "link": lp["source_link"],
                "body": str(data.get("body") or "").strip(),
            },
            reason=f"{lp['counterpart']}: {lp['title']} — {days} days overdue",
            refs=[f"loop:{lp['id']}", f"item:{lp['item_id']}"],
            scopes=list(lp["scopes"]),
            item_id=lp["item_id"],
        )
        done += 1
    return done


# --- delegation -------------------------------------------------------------------------------


def delegate_for(conn: Conn, item_id: int, owner: set[str]) -> dict[str, Any] | None:
    """The teammate whose ClickUp tasks this email resembles most, with their usual list."""
    rows = conn.execute(
        """
        SELECT t.metadata, 1 - (t.embedding <=> i.embedding) AS sim
        FROM items i JOIN items t ON t.kind = 'clickup_task' AND t.embedding IS NOT NULL
                                 AND NOT t.hidden
        WHERE i.id = %s AND i.embedding IS NOT NULL
        ORDER BY t.embedding <=> i.embedding LIMIT %s
        """,
        (item_id, SIMILAR_TASKS),
    ).fetchall()
    close = [r["metadata"] for r in rows if r["sim"] >= TASK_SIMILARITY]
    people: Counter[tuple[str, str]] = Counter()
    lists: dict[tuple[str, str], Counter[str]] = {}
    for meta in close:
        for name, email in zip(
            meta.get("assignees") or [], meta.get("assignee_emails") or [], strict=False
        ):
            if not email or email in owner:
                continue
            key = (name or email, email)
            people[key] += 1
            lists.setdefault(key, Counter())[f"{meta.get('list_id')}|{meta.get('list') or ''}"] += 1
    if not people:
        return None
    (name, email), n = people.most_common(1)[0]
    if n < MIN_SHARE:
        return None
    list_id, _, list_name = lists[(name, email)].most_common(1)[0][0].partition("|")
    return {"name": name, "email": email, "tasks": n, "list_id": list_id, "list": list_name}


def delegations(conn: Conn, config: Config, now: datetime) -> int:
    from kb.assistant import suggestions

    if not allowed(conn, "delegate", now):
        return 0
    owner = loops.owner_emails(conn, config)
    done = 0
    for r in conn.execute(
        """
        SELECT DISTINCT ON (t.item_id) t.item_id, i.title, coalesce(i.summary, '') AS summary,
               i.scopes, i.locator
        FROM triage t JOIN items i ON i.id = t.item_id
        WHERE t.class IN ('needs_reply', 'important') AND t.done_at IS NULL
          AND i.last_activity_at > %s AND i.embedding IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM suggestions s WHERE s.kind = 'delegate'
                          AND s.item_id = t.item_id)
        ORDER BY t.item_id DESC LIMIT 5
        """,
        (now - timedelta(days=2),),
    ).fetchall():
        who = delegate_for(conn, r["item_id"], owner)
        if who is None:
            continue
        link = r["locator"] if str(r["locator"] or "").startswith("https://") else ""
        suggestions.propose(
            conn,
            "delegate",
            {
                "list_id": who["list_id"],
                "name": r["title"] or "(no subject)",
                "description": "\n\n".join(x for x in (r["summary"], link) if x),
                "assignee_emails": [who["email"]],
                "assignee_name": who["name"],
                "due_date": None,
            },
            reason=f"{who['name']} handles similar tasks ({who['tasks']} in {who['list']})",
            refs=[f"item:{r['item_id']}"],
            scopes=list(r["scopes"]),
            item_id=r["item_id"],
        )
        done += 1
        if not allowed(conn, "delegate", now):
            break
    return done


def cycle(conn: Conn, config: Config, llm: StructuredLlm | None, now: datetime) -> int:
    n = delegations(conn, config, now)
    within = distill.month_spend_usd(conn, now.date()) < settings_store.budget_usd(conn, config)
    if llm is not None and within:
        try:
            n += nudges(conn, config, llm, now)
        except Exception:
            log.exception("nudge drafting failed")
    return n
