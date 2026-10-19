"""Weekly review (Friday) and weekly plan (Monday) — assistant-routines spec.

The review covers Monday 00:00 to now; the plan recaps the previous Monday to Sunday week and
proposes up to five priorities for the coming week, each with a reason and cited sources. When the
owner accepts (or edits) the plan, the morning briefs of that week list its priorities.
"""

from __future__ import annotations

import logging
from collections import Counter
from datetime import date, datetime, time, timedelta
from typing import Any

from psycopg.types.json import Jsonb

from kb import distill, loops, settings_store
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm
from kb.routines import KYIV, factpack
from kb.routines.briefs import (
    _COMMON,
    AI_SOURCE,
    Section,
    data_only,
    loop_item,
    pack_text,
    store,
    validate_refs,
)
from kb.routines.factpack import FactPack

log = logging.getLogger(__name__)

MAX_PRIORITIES = 5

PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sections", "priorities"],
    "properties": {
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "text", "refs"],
                "properties": {
                    "title": {"type": "string"},
                    "text": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "reason", "refs"],
                "properties": {
                    "title": {"type": "string"},
                    "reason": {"type": "string"},
                    "refs": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
}

REVIEW_PROMPT = (
    _COMMON
    + """
This is the WEEKLY REVIEW (Friday). Write one section per scope that had activity this week (skip
scopes without activity): key conversations, decisions made, who the owner worked with most.
Add a section on open loops that are aging. In `focus`, pick at most 3 things to settle before
the weekend or first thing Monday."""
)

PLAN_PROMPT = (
    _COMMON
    + """
This is the WEEKLY PLAN (Monday). First recap last week in 2-4 sections (by scope). Then propose
at most 5 `priorities` for this week: each a short imperative title, a one-line reason, and refs
to the conversations or loops it is based on. Prefer overdue or due-this-week loops, promises the
owner made, and decisions waiting for the owner."""
)


def week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def review_window(now: datetime) -> tuple[datetime, datetime]:
    monday = week_start(now.astimezone(KYIV).date())
    return datetime.combine(monday, time(0, 0), tzinfo=KYIV), now


def plan_window(now: datetime) -> tuple[datetime, datetime]:
    monday = week_start(now.astimezone(KYIV).date())
    start = datetime.combine(monday - timedelta(days=7), time(0, 0), tzinfo=KYIV)
    return start, datetime.combine(monday, time(0, 0), tzinfo=KYIV)


def _numbers(conn: Conn, pack: FactPack) -> Section:
    start, end = pack.window
    loop_counts = conn.execute(
        "SELECT count(*) FILTER (WHERE created_at >= %(s)s AND created_at < %(e)s) AS opened,"
        " count(*) FILTER (WHERE status = 'done' AND closed_at >= %(s)s AND closed_at < %(e)s)"
        " AS closed FROM loops",
        {"s": start, "e": end},
    ).fetchone()
    facts = {f.ref: f for items in pack.by_scope.values() for f in items}.values()
    decisions = sum(1 for f in facts if f.outcome)
    people = Counter(p for f in facts for p in f.participants if p)
    top = ", ".join(f"{name} ({n})" for name, n in people.most_common(5))
    parts = [
        f"{pack.counts.get('email_thread', 0)} email threads",
        f"{pack.counts.get('tg_conversation', 0)} chats",
        f"{decisions} decisions",
        f"loops opened {loop_counts['opened'] if loop_counts else 0}"
        f" / closed {loop_counts['closed'] if loop_counts else 0}",
    ]
    text = " · ".join(parts) + (f". Most contact: {top}" if top else "")
    return Section("This week in numbers", text, kind="note")


def _ai(
    conn: Conn,
    pack: FactPack,
    llm: StructuredLlm | None,
    config: Config,
    prompt: str,
    schema: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, float, Section | None]:
    if llm is None or not (pack.by_scope or any(pack.loops.values())):
        return None, 0.0, None
    if distill.month_spend_usd(conn, pack.window[1].date()) >= settings_store.budget_usd(
        conn, config
    ):
        note = Section("AI budget reached", "This review lists activity without AI.", kind="note")
        return None, 0.0, note
    from kb.routines.briefs import SCHEMA

    model = config.llm.briefs_model()
    try:
        data, usage = llm.structured(
            model, prompt, pack_text(pack), schema or SCHEMA, f"{pack.routine}_brief", "low"
        )
    except Exception:
        log.exception("AI step of %s failed", pack.routine)
        return None, 0.0, Section("AI unavailable", "Listed without AI.", kind="note")
    distill.record_usage(conn, AI_SOURCE, model, pack.routine, usage)
    return data, distill.cost_usd(model, usage), None


def _weekly_loops(conn: Conn, now: datetime) -> dict[str, list[dict[str, Any]]]:
    open_rows = loops.list_loops(conn, now, "open")
    week_end = week_start(loops.kyiv_today(now)) + timedelta(days=6)
    return {
        "due": [
            lp for lp in open_rows if lp["due_date"] and lp["due_date"] <= week_end.isoformat()
        ],
        "aging": [lp for lp in open_rows if not lp["due_date"] and (lp["age_days"] or 0) >= 7],
    }


def _audit(conn: Conn, now: datetime, pack: FactPack) -> list[Section]:
    """Where attention went vs goals, goals without progress, and the week's decisions."""
    from kb import focus

    out = []
    if lines := focus.attention(conn, *pack.window):
        out.append(Section("Where attention went", "\n".join(lines), kind="note"))
    if neglected := focus.neglected_goals(conn, now):
        text = "\n".join(f"{g['title']} ({g['scope']}) — {g['first_step']}" for g in neglected)
        out.append(Section("No progress (14 days)", text, kind="note"))
    for scope, items in focus.decisions(conn, *pack.window).items():
        out.append(Section(f"Decisions · {scope}", "", items, kind="group"))
    return out


def run_review(conn: Conn, now: datetime, llm: StructuredLlm | None, config: Config) -> int:
    pack = factpack.build(conn, "weekly_review", review_window(now))
    pack.loops = _weekly_loops(conn, now)
    data, cost, note = _ai(conn, pack, llm, config, REVIEW_PROMPT, None)
    sections: list[Section] = [note] if note else []
    if data:
        sections += validate_refs(data, pack)
    sections.append(_numbers(conn, pack))
    sections += _audit(conn, now, pack)
    for key, title in (("due", "Due this week"), ("aging", "Open loops by age")):
        if rows := sorted(pack.loops.get(key, []), key=lambda lp: -(lp["age_days"] or 0)):
            sections.append(Section(title, "", [loop_item(lp) for lp in rows], kind="group"))
    sections += data_only(pack)
    return store(conn, pack, sections, "ai" if data else "data", cost)


def _priorities(data: dict[str, Any] | None, pack: FactPack) -> list[dict[str, Any]]:
    if not data:
        return []
    allowed = {f.ref for items in pack.by_scope.values() for f in items}
    allowed |= {lp["ref"] for rows in pack.loops.values() for lp in rows}
    out = []
    for p in data.get("priorities") or []:
        refs = list(dict.fromkeys(r for r in p.get("refs") or [] if r in allowed))
        if refs and p.get("title"):
            out.append({"title": str(p["title"]), "reason": str(p.get("reason", "")), "refs": refs})
    return out[:MAX_PRIORITIES]


def run_plan(conn: Conn, now: datetime, llm: StructuredLlm | None, config: Config) -> int:
    pack = factpack.build(conn, "weekly_plan", plan_window(now))
    pack.loops = _weekly_loops(conn, now)
    data, cost, note = _ai(conn, pack, llm, config, PLAN_PROMPT, PLAN_SCHEMA)
    priorities = _priorities(data, pack)
    sections: list[Section] = [note] if note else []
    if data:
        sections += validate_refs({"sections": data.get("sections") or [], "focus": []}, pack)
    if priorities:
        text = "\n".join(f"{n}. {p['title']} — {p['reason']}" for n, p in enumerate(priorities, 1))
        sections.append(Section("Proposed priorities", text, kind="note"))
    for key, title in (("due", "Due this week"), ("aging", "Aging loops to chase")):
        if rows := pack.loops.get(key):
            sections.append(Section(title, "", [loop_item(lp) for lp in rows], kind="group"))
    sections += data_only(pack)
    brief_id = store(conn, pack, sections, "ai" if data else "data", cost)
    conn.execute(
        "INSERT INTO weekly_plans (brief_id, week_start, proposed) VALUES (%s, %s, %s)",
        (brief_id, week_start(loops.kyiv_today(now)), Jsonb(priorities)),
    )
    return brief_id


def accept_plan(
    conn: Conn, brief_id: int, now: datetime, priorities: list[dict[str, Any]] | None = None
) -> None:
    plan = conn.execute("SELECT * FROM weekly_plans WHERE brief_id = %s", (brief_id,)).fetchone()
    if plan is None:
        raise ValueError(f"brief {brief_id} is not a weekly plan")
    chosen = plan["proposed"] if priorities is None else priorities
    clean = [
        {
            "title": str(p["title"]).strip(),
            "reason": str(p.get("reason", "")),
            "refs": list(p.get("refs") or []),
        }
        for p in chosen
        if str(p.get("title", "")).strip()
    ][:MAX_PRIORITIES]
    conn.execute(
        "UPDATE weekly_plans SET accepted = %s, accepted_at = %s, edited = %s WHERE brief_id = %s",
        (Jsonb(clean), now, priorities is not None and clean != plan["proposed"], brief_id),
    )


def accepted_priorities(conn: Conn, now: datetime) -> list[dict[str, Any]]:
    """This week's accepted priorities (latest accepted plan of the current week)."""
    row = conn.execute(
        "SELECT accepted FROM weekly_plans WHERE week_start = %s AND accepted IS NOT NULL"
        " ORDER BY accepted_at DESC LIMIT 1",
        (week_start(loops.kyiv_today(now)),),
    ).fetchone()
    return list(row["accepted"]) if row else []
