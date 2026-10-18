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

from kb import distill
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
- Every section must cite the conversations it is about in `refs`, exactly as written in the pack
  (e.g. "item:123"). A section without refs will be discarded.
- Be concrete and brief: 1-3 sentences per section, names and amounts where the pack has them.
- Skip small talk, newsletters and notifications unless they need the owner.
- Group by project/area (scope) when useful; scopes: personal, digisoft, quokka, rdim, unsorted."""

PROMPTS = {
    "morning": _COMMON
    + """
This is the MORNING brief covering activity since last evening. Write 2-6 sections: what happened
per scope, anything that needs the owner's reply or decision first. In `focus`, pick at most 3
conversations the owner should handle first today, each with a one-line reason.""",
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
    if total == 0:
        return f"{title}: nothing new"
    scopes = len(pack.by_scope)
    return (
        f"{title}: {total} conversation{'s' if total != 1 else ''}"
        f" across {scopes} scope{'s' if scopes != 1 else ''}"
    )


def coming_up(now: datetime) -> Section | None:
    """The rest of today's routines (the morning brief lists them)."""
    from kb.routines.scheduler import RoutineSettings

    s = RoutineSettings()
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
    seen: set[str] = set()
    for scope, facts in pack.by_scope.items():
        lines.append(f"\n## {scope}")
        for f in facts:
            lines.append(_fact_line(f) if f.ref not in seen else f"[{f.ref}] (see above)")
            seen.add(f.ref)
    return "\n".join(lines)


def validate_refs(data: dict[str, Any], pack: FactPack) -> list[Section]:
    """AI sections and focus with only refs that exist in the pack; unsupported ones dropped."""
    facts = {f.ref: f for items in pack.by_scope.values() for f in items}
    out: list[Section] = []
    focus_items: list[dict[str, Any]] = []
    for entry in data.get("focus") or []:
        ref = entry.get("ref")
        if ref in facts and ref not in {i["ref"] for i in focus_items}:
            focus_items.append({**facts[ref].to_dict(), "reason": str(entry.get("reason", ""))})
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
                [facts[r].to_dict() for r in refs],
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
    sections: list[Section] = []
    mode, cost = "data", 0.0
    has_activity = bool(pack.by_scope)
    if has_activity and llm is not None:
        spent = distill.month_spend_usd(conn, now.date())
        if spent >= config.llm.monthly_budget_usd:
            sections.append(
                Section(
                    "AI budget reached",
                    f"This month's AI budget (${config.llm.monthly_budget_usd:.0f}) is used up;"
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
    if pack.routine == "morning" and (upcoming := coming_up(now)):
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
    }


def _run_revision(conn: Conn, now: datetime, llm: StructuredLlm | None, config: Config) -> int:
    from kb.routines import triage

    return triage.run_pass(conn, now, llm, config)


def default_llm(config: Config) -> StructuredLlm | None:
    client = distill.default_client(config)
    return cast(StructuredLlm, client) if isinstance(client, distill.OpenAIClient) else None
