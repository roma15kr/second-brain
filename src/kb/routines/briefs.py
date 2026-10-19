"""Briefs: written from a fact pack and stored as a page (design D5).

The AI only writes prose about facts in the pack and must cite them by ref (`item:123`); refs
that are not in the pack are dropped, and a section left without refs is dropped too, so a brief
never contains a claim without a source. Every brief also lists all activity per scope from data.
Without an AI client, above the monthly budget, or when the AI call fails, the brief is data-only.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

from psycopg.types.json import Jsonb

from kb import distill, settings_store
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm, Usage
from kb.routines import KYIV, RoutineName
from kb.routines.factpack import FactPack, ItemFact

log = logging.getLogger(__name__)

AI_SOURCE = "_routines"  # llm_usage.source_id for routine calls
MAX_FOCUS = 3
KIND_WORDS = {
    "email_thread": ("email thread", "email threads"),
    "tg_conversation": ("chat", "chats"),
    "clickup_task": ("ClickUp task", "ClickUp tasks"),
    "clickup_chat": ("ClickUp chat day", "ClickUp chat days"),
}
TITLES = {
    "morning": "Morning brief",
    "revision": "Mail revision",
    "evening": "Evening wrap",
    "weekly_review": "Weekly review",
    "weekly_plan": "Weekly plan",
}

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["sections", "focus"],
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
        "focus": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "reason"],
                "properties": {"ref": {"type": "string"}, "reason": {"type": "string"}},
            },
        },
    },
}

_COMMON = """You are the owner's personal assistant writing a short brief in English from a fact
pack of their own email threads and Telegram chats. Rules:
- Use only facts from the pack. Never invent people, numbers, dates or decisions.
- Every section must cite the conversations or loops it is about in `refs`, exactly as written in
  the pack (e.g. "item:123", "loop:45"). A section without refs will be discarded.
- Be concrete and brief: 1-3 sentences per section, names and amounts where the pack has them.
- Skip small talk, newsletters and notifications unless they need the owner.
- Group by project/area (scope) when useful; scopes: personal, digisoft, quokka, rdim, unsorted."""

PROMPTS = {
    "morning": _COMMON
    + """
This is the MORNING brief covering activity since last evening. Write 2-6 sections: what happened
per scope, anything that needs the owner's reply or decision first. If the pack lists this week's
priorities, add one section on what moved on them (cite the related items). In `focus`, pick at
most 3 conversations the owner should handle first today, each with a one-line reason.""",
    "evening": _COMMON
    + """
This is the EVENING wrap of today. Write 2-6 sections: decisions and outcomes reached today,
open questions still waiting for the owner, and what carries over to tomorrow. In `focus`, pick at
most 3 conversations to start with tomorrow, each with a one-line reason.""",
}


@dataclass
class Section:
    title: str
    text: str
    items: list[dict[str, Any]] = field(default_factory=list)
    kind: str = "data"  # ai | focus | data | note

    @property
    def refs(self) -> list[str]:
        return [i["ref"] for i in self.items]

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "text": self.text,
            "refs": self.refs,
            "items": self.items,
            "kind": self.kind,
        }


# --- data-only rendering --------------------------------------------------------------------


def _count_words(counts: dict[str, int]) -> str:
    parts = []
    for kind, n in sorted(counts.items()):
        one, many = KIND_WORDS.get(kind, (kind, kind))
        parts.append(f"{n} {one if n == 1 else many}")
    return ", ".join(parts)


def data_only(pack: FactPack) -> list[Section]:
    """One section per scope listing its conversations; no AI."""
    sections = []
    for scope, facts in pack.by_scope.items():
        counts: dict[str, int] = {}
        for f in facts:
            counts[f.kind] = counts.get(f.kind, 0) + 1
        sections.append(
            Section(title=scope, text=_count_words(counts), items=[f.to_dict() for f in facts])
        )
    if not sections:
        sections.append(Section(title="Quiet", text="No new conversations in this period."))
    return sections


def headline(pack: FactPack) -> str:
    total = sum(pack.counts.values())
    title = TITLES[pack.routine]
    needs = []
    if n := len(pack.loops.get("needs_reply", [])):
        needs.append(f"{n} need{'s' if n == 1 else ''} your reply")
    if n := len(pack.loops.get("due", [])):
        needs.append(f"{n} due")
    prefix = ", ".join(needs)
    if total == 0:
        return f"{title}: {prefix}" if prefix else f"{title}: nothing new"
    scopes = len(pack.by_scope)
    activity = (
        f"{total} conversation{'s' if total != 1 else ''}"
        f" across {scopes} scope{'s' if scopes != 1 else ''}"
    )
    return f"{title}: {prefix} · {activity}" if prefix else f"{title}: {activity}"


DIRECTION = {
    "needs_reply": "Reply to",
    "i_owe": "You owe",
    "owed_to_me": "Owed to you by",
    "manual": "Your task",
}


def loop_item(lp: dict[str, Any]) -> dict[str, Any]:
    """A loop rendered like a brief item (links to its source message)."""
    who = f"{DIRECTION.get(lp['kind'], '')} {lp['counterpart']}".strip()
    when = ""
    if lp["overdue"]:
        when = f" · overdue since {lp['due_date']}"
    elif lp["due_date"]:
        when = f" · due {lp['due_date']}"
    elif lp.get("age_days"):
        when = f" · {lp['age_days']} days open"
    if lp.get("priority_reason"):
        when += f" · {lp['priority_reason']}"
    return {
        "ref": lp["ref"],
        "id": lp["id"],
        "kind": "loop",
        "title": lp["title"],
        "summary": who + when,
        "outcome": None,
        "link": lp["link"],
        "last_activity_at": lp["opened_at"] or "",
        "scopes": lp["scopes"],
        "participants": [lp["counterpart"]] if lp["counterpart"] else [],
        "overdue": lp["overdue"],
    }


LOOP_SECTIONS = {
    "morning": [("due", "Due today & overdue"), ("needs_reply", "Waiting for your reply")],
    "evening": [
        ("closed", "Closed today"),
        ("opened", "Opened today"),
        ("due", "Due today & overdue"),
        ("needs_reply", "Still waiting for your reply"),
    ],
}


def early_meetings(conn: Conn, now: datetime) -> list[dict[str, Any]]:
    """Meetings before 10:00 today, linked to their prep (calendar-meetings: preparation)."""
    from kb import meetings

    out = []
    for m in meetings.early_meetings(conn, now):
        prep = m.get("prep") or {}
        agenda = "; ".join(a["text"] for a in prep.get("agenda", [])[:3])
        people = ", ".join(p["name"] for p in prep.get("people", [])[:4])
        start = datetime.fromisoformat(m["start"]).astimezone(KYIV)
        out.append(
            {
                "ref": f"meeting:{m['id']}",
                "id": m["id"],
                "kind": "meeting",
                "title": f"{start:%H:%M} {m['title']}",
                "summary": " · ".join(x for x in (people, agenda) if x) or m["calendar"],
                "outcome": None,
                "link": f"/meetings/{m['id']}",
                "last_activity_at": m["start"],
                "scopes": m["scopes"],
                "participants": [],
            }
        )
    return out


def clickup_due(conn: Conn, owner: set[str], now: datetime) -> list[dict[str, Any]]:
    """The owner's ClickUp tasks due today or overdue and not closed (clickup-integration spec)."""
    if not owner:
        return []
    end_of_today = datetime.combine(
        now.astimezone(KYIV).date(), datetime.max.time(), tzinfo=KYIV
    ).isoformat()
    rows = conn.execute(
        """
        SELECT id, title, locator, scopes, metadata, last_activity_at FROM items
        WHERE kind = 'clickup_task' AND NOT hidden
          AND metadata->>'due_date' IS NOT NULL AND (metadata->>'due_date')::timestamptz <= %s
          AND coalesce(metadata->>'status_type', '') NOT IN ('closed', 'done')
          AND metadata->'assignee_emails' ?| %s
        ORDER BY (metadata->>'due_date')::timestamptz
        """,
        (end_of_today, sorted(owner)),
    ).fetchall()
    out = []
    for r in rows:
        due = datetime.fromisoformat(r["metadata"]["due_date"]).astimezone(KYIV).date()
        late = due < now.astimezone(KYIV).date()
        out.append(
            {
                "ref": f"item:{r['id']}",
                "id": r["id"],
                "kind": "clickup_task",
                "title": r["title"],
                "summary": f"{r['metadata'].get('list') or 'ClickUp'} · "
                + (f"overdue since {due.isoformat()}" if late else "due today"),
                "outcome": None,
                "link": r["locator"],
                "last_activity_at": r["last_activity_at"].isoformat()
                if r["last_activity_at"]
                else "",
                "scopes": list(r["scopes"]),
                "participants": [],
                "overdue": late,
            }
        )
    return out


def loop_sections(pack: FactPack) -> list[Section]:
    out = []
    for key, title in LOOP_SECTIONS.get(pack.routine, []):
        if rows := pack.loops.get(key):
            out.append(Section(title, "", [loop_item(lp) for lp in rows], kind="group"))
    return out


def coming_up(conn: Conn, now: datetime) -> Section | None:
    """The rest of today's routines (the morning brief lists them)."""
    s = settings_store.routine_settings(conn)
    local = now.astimezone(KYIV)
    names = {"revision": "Mail revision", "evening": "Evening wrap"}
    parts = []
    for name, label in names.items():
        times = [t for t in getattr(s, name) if t > local.time()]
        if times:
            parts.append(f"{label} {', '.join(t.strftime('%H:%M') for t in times)}")
    if local.weekday() == s.weekly_review[0] and s.weekly_review[1] > local.time():
        parts.append(f"Weekly review {s.weekly_review[1].strftime('%H:%M')}")
    return Section("Coming up", " · ".join(parts), kind="note") if parts else None


# --- AI step --------------------------------------------------------------------------------


def _fact_line(f: ItemFact) -> str:
    kind = KIND_WORDS.get(f.kind, (f.kind, f.kind))[0]
    when = f.last_activity_at.astimezone(KYIV).strftime("%a %H:%M")
    parts = [f"[{f.ref}] ({kind}, {when}) {f.title or '(no subject)'}"]
    if f.summary:
        parts.append(f"Summary: {f.summary}")
    if f.outcome:
        parts.append(f"Outcome: {f.outcome}")
    if f.participants:
        parts.append(f"People: {', '.join(f.participants[:6])}")
    return " | ".join(parts)


def pack_text(pack: FactPack) -> str:
    lines = [
        f"Routine: {pack.routine}",
        f"Window: {pack.window[0].astimezone(KYIV):%a %d %b %H:%M} to "
        f"{pack.window[1].astimezone(KYIV):%a %d %b %H:%M} (Kyiv)",
    ]
    if pack.priorities:
        lines.append("\n## This week's priorities (accepted by the owner)")
        lines += [f"- {p['title']} ({p.get('reason', '')})" for p in pack.priorities]
    for key, title in LOOP_SECTIONS.get(pack.routine, []):
        if rows := pack.loops.get(key):
            lines.append(f"\n## {title}")
            lines += [f"[{lp['ref']}] {loop_item(lp)['summary']}: {lp['title']}" for lp in rows]
    seen: set[str] = set()
    for scope, facts in pack.by_scope.items():
        lines.append(f"\n## {scope}")
        for f in facts:
            lines.append(_fact_line(f) if f.ref not in seen else f"[{f.ref}] (see above)")
            seen.add(f.ref)
    return "\n".join(lines)


def validate_refs(data: dict[str, Any], pack: FactPack) -> list[Section]:
    """AI sections and focus with only refs that exist in the pack; unsupported ones dropped."""
    facts: dict[str, dict[str, Any]] = {
        f.ref: f.to_dict() for items in pack.by_scope.values() for f in items
    }
    facts.update({lp["ref"]: loop_item(lp) for rows in pack.loops.values() for lp in rows})
    out: list[Section] = []
    focus_items: list[dict[str, Any]] = []
    for entry in data.get("focus") or []:
        ref = entry.get("ref")
        if ref in facts and ref not in {i["ref"] for i in focus_items}:
            focus_items.append({**facts[ref], "reason": str(entry.get("reason", ""))})
    if focus_items:
        out.append(Section("Focus", "", focus_items[:MAX_FOCUS], kind="focus"))
    for s in data.get("sections") or []:
        refs = list(dict.fromkeys(r for r in s.get("refs") or [] if r in facts))
        if not refs:
            log.info("dropping AI section without valid refs: %s", s.get("title"))
            continue
        out.append(
            Section(
                str(s.get("title", "")),
                str(s.get("text", "")),
                [facts[r] for r in refs],
                kind="ai",
            )
        )
    return out


def generate(pack: FactPack, llm: StructuredLlm, model: str) -> tuple[list[Section], Usage]:
    data, usage = llm.structured(
        model, PROMPTS[pack.routine], pack_text(pack), SCHEMA, f"{pack.routine}_brief", "low"
    )
    return validate_refs(data, pack), usage


# --- storing and running --------------------------------------------------------------------


def store(conn: Conn, pack: FactPack, sections: list[Section], mode: str, cost: float = 0.0) -> int:
    row = conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode,"
        " cost_usd) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            pack.routine,
            pack.window[0],
            pack.window[1],
            headline(pack),
            Jsonb([s.to_dict() for s in sections]),
            mode,
            round(cost, 4),
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def write_brief(
    conn: Conn,
    pack: FactPack,
    now: datetime,
    llm: StructuredLlm | None,
    config: Config,
) -> int:
    """AI sections (when allowed) + all activity per scope from data, then stored."""
    from kb import loops

    pack.loops = loops.for_brief(conn, pack.routine, pack.window, now)
    if replies := pack.loops.get("needs_reply"):
        from kb.assistant import priority

        ids = [lp["item_id"] for lp in replies if lp["item_id"]]
        prio = priority.assess(conn, ids, loops.owner_emails(conn, config), now)
        for lp in replies:
            if (p := prio.get(lp["item_id"])) is not None and p.reason:
                lp["priority_reason"] = p.reason
        order = {i: n for n, i in enumerate(priority.ordered(prio, ids))}
        replies.sort(key=lambda lp: order.get(lp["item_id"], len(order)))
    if pack.routine == "morning":
        from kb.routines import weekly

        pack.priorities = weekly.accepted_priorities(conn, now)
    sections: list[Section] = []
    mode, cost = "data", 0.0
    has_activity = bool(pack.by_scope) or any(pack.loops.values())
    if has_activity and llm is not None:
        spent = distill.month_spend_usd(conn, now.date())
        budget = settings_store.budget_usd(conn, config)
        if spent >= budget:
            sections.append(
                Section(
                    "AI budget reached",
                    f"This month's AI budget (${budget:.0f}) is used up;"
                    " this brief lists activity without AI summaries.",
                    kind="note",
                )
            )
        else:
            model = config.llm.briefs_model()
            try:
                ai_sections, usage = generate(pack, llm, model)
            except Exception:
                log.exception("AI step of the %s brief failed; storing data-only", pack.routine)
                sections.append(
                    Section("AI unavailable", "Activity below is listed without AI.", kind="note")
                )
            else:
                distill.record_usage(conn, AI_SOURCE, model, pack.routine, usage)
                cost = distill.cost_usd(model, usage)
                if ai_sections:
                    sections.extend(ai_sections)
                    mode = "ai"
    if pack.priorities:
        text = "\n".join(f"{n}. {p['title']}" for n, p in enumerate(pack.priorities, 1))
        sections.append(Section("This week's priorities", text, kind="note"))
    sections.extend(loop_sections(pack))
    if pack.routine in ("morning", "evening"):
        from kb.connectors import clickup

        if for_me := clickup.for_brief(conn, pack.window):
            sections.append(Section("For you in ClickUp", "", for_me, kind="group"))
    if pack.routine == "morning":
        from kb import loops

        if due_tasks := clickup_due(conn, loops.owner_emails(conn, config), now):
            sections.append(Section("ClickUp: due today & overdue", "", due_tasks, kind="group"))
    if pack.routine == "morning" and (early := early_meetings(conn, now)):
        sections.append(Section("Meetings before 10:00", "", early, kind="group"))
    if pack.routine == "morning" and (upcoming := coming_up(conn, now)):
        sections.append(upcoming)
    sections.extend(data_only(pack))
    return store(conn, pack, sections, mode, cost)


def to_dict(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "routine": row["routine"],
        "title": TITLES.get(row["routine"], row["routine"]),
        "headline": row["headline"],
        "window_start": row["window_start"].isoformat(),
        "window_end": row["window_end"].isoformat(),
        "mode": row["mode"],
        "sections": row["sections"],
        "cost_usd": float(row["cost_usd"]),
        "push": bool(row.get("push", True)),
        "created_at": row["created_at"].isoformat(),
    }


def latest(conn: Conn, routines: list[RoutineName]) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM briefs WHERE routine = ANY(%s) ORDER BY created_at DESC, id DESC LIMIT 1",
        (routines,),
    ).fetchone()
    return to_dict(row) if row else None


def run_morning(
    conn: Conn, now: datetime, llm: StructuredLlm | None = None, config: Config | None = None
) -> int:
    from kb.routines import factpack

    pack = factpack.build(conn, "morning", factpack.morning_window(now))
    return write_brief(conn, pack, now, llm, config or Config())


def run_evening(
    conn: Conn, now: datetime, llm: StructuredLlm | None = None, config: Config | None = None
) -> int:
    from kb.routines import factpack

    pack = factpack.build(conn, "evening", factpack.evening_window(now))
    return write_brief(conn, pack, now, llm, config or Config())


def runners(
    config: Config | None = None, llm: StructuredLlm | None = None
) -> dict[RoutineName, Callable[[Conn, datetime], int]]:
    """Routines that can run today; the scheduler skips the others (they arrive in later tasks)."""
    cfg = config or Config()
    return {
        "morning": lambda conn, now: run_morning(conn, now, llm, cfg),
        "evening": lambda conn, now: run_evening(conn, now, llm, cfg),
        "revision": lambda conn, now: _run_revision(conn, now, llm, cfg),
        "weekly_review": lambda conn, now: _weekly(conn, now, llm, cfg, "review"),
        "weekly_plan": lambda conn, now: _weekly(conn, now, llm, cfg, "plan"),
    }


def _weekly(
    conn: Conn, now: datetime, llm: StructuredLlm | None, config: Config, which: str
) -> int:
    from kb.routines import weekly

    run = weekly.run_review if which == "review" else weekly.run_plan
    return run(conn, now, llm, config)


def _run_revision(conn: Conn, now: datetime, llm: StructuredLlm | None, config: Config) -> int:
    from kb.routines import triage

    return triage.run_pass(conn, now, llm, config)


def default_llm(config: Config) -> StructuredLlm | None:
    client = distill.default_client(config)
    return cast(StructuredLlm, client) if isinstance(client, distill.OpenAIClient) else None
