"""Mail revision passes (assistant-routines spec, design D6).

Each pass takes email threads with activity since the previous pass and sorts them into needs
reply / important / FYI / noise, with a one-line next action. Sender preferences decide first
(no AI); threads where the owner wrote last need nothing from the owner; the rest go to the cheap
model. A pass is pushed only when something needs a reply or is important.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from email.utils import parseaddr
from typing import Any, Literal

from psycopg.types.json import Jsonb

from kb import distill, loops, settings_store
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm
from kb.routines.briefs import AI_SOURCE, Section

log = logging.getLogger(__name__)

TriageClass = Literal["needs_reply", "important", "fyi", "noise"]
CLASSES: tuple[TriageClass, ...] = ("needs_reply", "important", "fyi", "noise")
GROUP_TITLES = {
    "needs_reply": "Needs reply",
    "important": "Important",
    "fyi": "FYI",
    "noise": "Noise",
}
FIRST_PASS_LOOKBACK = timedelta(hours=24)
CHUNK = 30

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["items"],
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ref", "class", "action", "reason"],
                "properties": {
                    "ref": {"type": "string"},
                    "class": {"type": "string", "enum": list(CLASSES)},
                    "action": {"type": "string"},
                    "reason": {"type": "string"},
                },
            },
        }
    },
}

PROMPT = """You triage the owner's new email threads. For each thread (by its ref) choose:
- needs_reply: a person asks the owner something or waits for the owner's answer/decision;
- important: no reply needed but the owner should know today (money, contracts, deadlines,
  problems, key partners);
- fyi: worth a glance later (updates, confirmations, receipts the owner expects);
- noise: newsletters, promotions, automatic notifications, spam-like mail.
`action`: for needs_reply and important, one short imperative next step in English (e.g. "Send
the November price list to Olga"); empty for fyi and noise. `reason`: a few words why.
Use only the given text. Return every ref exactly once."""


@dataclass
class Candidate:
    item_id: int
    title: str
    summary: str
    scopes: list[str]
    link: str | None
    last_activity_at: datetime
    sender: str  # address of the last message's author
    excerpt: str

    @property
    def ref(self) -> str:
        return f"item:{self.item_id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "id": self.item_id,
            "kind": "email_thread",
            "title": self.title,
            "summary": self.summary,
            "outcome": None,
            "link": self.link,
            "last_activity_at": self.last_activity_at.isoformat(),
            "scopes": self.scopes,
            "participants": [self.sender] if self.sender else [],
        }


@dataclass
class Decision:
    cls: TriageClass
    action: str = ""
    reason: str = ""


def owner_addresses(conn: Conn, config: Config) -> set[str]:
    """The owner's own email addresses (mailboxes + Settings)."""
    from kb import loops

    return loops.owner_emails(conn, config)


def _address(author: str | None) -> str:
    return parseaddr(author or "")[1].lower()


def window_start(conn: Conn, now: datetime) -> datetime:
    row = conn.execute(
        "SELECT max(window_end) AS w FROM briefs WHERE routine = 'revision' AND window_end < %s",
        (now,),
    ).fetchone()
    return row["w"] if row and row["w"] else now - FIRST_PASS_LOOKBACK


def candidates(conn: Conn, since: datetime, until: datetime) -> list[Candidate]:
    rows = conn.execute(
        """
        SELECT i.id, coalesce(i.title, '') AS title,
               coalesce(i.summary, i.question, '') AS summary, i.scopes, i.locator,
               i.last_activity_at, m.author, right(m.body, 800) AS excerpt
        FROM items i
        JOIN LATERAL (
            SELECT author, body FROM messages
            WHERE source_id = i.source_id AND unit_key = i.source_item_key AND NOT hidden
              AND NOT (coalesce(metadata->'labels', '[]'::jsonb) ?| array['\\Draft', 'Draft'])
            ORDER BY sent_at DESC LIMIT 1
        ) m ON true
        WHERE i.kind = 'email_thread' AND NOT i.hidden
          AND i.last_activity_at > %s AND i.last_activity_at <= %s
        ORDER BY i.last_activity_at DESC
        """,
        (since, until),
    ).fetchall()
    return [
        Candidate(
            item_id=r["id"],
            title=r["title"],
            summary=r["summary"],
            scopes=list(r["scopes"]),
            link=r["locator"] if str(r["locator"] or "").startswith("https://") else None,
            last_activity_at=r["last_activity_at"],
            sender=_address(r["author"]),
            excerpt=r["excerpt"] or "",
        )
        for r in rows
    ]


def sender_prefs(conn: Conn, addresses: list[str]) -> dict[str, str]:
    rows = conn.execute(
        "SELECT address, pref FROM sender_prefs WHERE address = ANY(%s)", (addresses,)
    ).fetchall()
    return {r["address"]: r["pref"] for r in rows}


def set_sender_pref(conn: Conn, address: str, pref: str | None) -> None:
    address = _address(address) or address.strip().lower()
    if pref is None:
        conn.execute("DELETE FROM sender_prefs WHERE address = %s", (address,))
        return
    if pref not in ("noise", "important"):
        raise ValueError("pref must be 'noise' or 'important'")
    conn.execute(
        "INSERT INTO sender_prefs (address, pref) VALUES (%s, %s) ON CONFLICT (address)"
        " DO UPDATE SET pref = EXCLUDED.pref, updated_at = now()",
        (address, pref),
    )


def _classify_ai(
    llm: StructuredLlm, model: str, todo: list[Candidate]
) -> tuple[dict[str, Decision], distill.Usage]:
    total = distill.Usage()
    out: dict[str, Decision] = {}
    for start in range(0, len(todo), CHUNK):
        chunk = todo[start : start + CHUNK]
        text = "\n\n".join(
            f"[{c.ref}] From: {c.sender or 'unknown'} | Subject: {c.title or '(no subject)'}\n"
            f"Summary: {c.summary or '-'}\nLatest message: {c.excerpt.strip()[:800]}"
            for c in chunk
        )
        data, usage = llm.structured(model, PROMPT, text, SCHEMA, "mail_triage", "low")
        total.input_tokens += usage.input_tokens
        total.output_tokens += usage.output_tokens
        refs = {c.ref for c in chunk}
        for d in data.get("items") or []:
            if d.get("ref") in refs and d.get("class") in CLASSES:
                out[d["ref"]] = Decision(
                    d["class"], str(d.get("action", "")), str(d.get("reason", ""))
                )
    return out, total


def classify(
    conn: Conn, config: Config, llm: StructuredLlm | None, items: list[Candidate], now: datetime
) -> tuple[dict[str, Decision], float, str | None]:
    """Decisions per ref, AI cost, and a note when AI was not used."""
    owner = owner_addresses(conn, config)
    prefs = sender_prefs(conn, [c.sender for c in items if c.sender])
    decisions: dict[str, Decision] = {}
    todo: list[Candidate] = []
    for c in items:
        if c.sender and c.sender in owner:
            decisions[c.ref] = Decision("fyi", "", "you wrote last")
        elif prefs.get(c.sender) == "noise":
            decisions[c.ref] = Decision("noise", "", "sender marked as noise")
        else:
            todo.append(c)
    note, cost = None, 0.0
    if todo and llm is None:
        note = "AI is off: these threads are listed without triage."
    elif todo and distill.month_spend_usd(conn, now.date()) >= settings_store.budget_usd(
        conn, config
    ):
        note = "This month's AI budget is used up: these threads are listed without triage."
    elif todo:
        assert llm is not None
        model = config.llm.model()
        try:
            ai, usage = _classify_ai(llm, model, todo)
        except Exception:
            log.exception("mail triage AI call failed")
            note = "AI was unavailable: these threads are listed without triage."
        else:
            distill.record_usage(conn, AI_SOURCE, model, "revision", usage)
            cost = distill.cost_usd(model, usage)
            decisions.update(ai)
    for c in todo:
        d = decisions.setdefault(c.ref, Decision("fyi", "", "not triaged"))
        if prefs.get(c.sender) == "important" and d.cls in ("fyi", "noise"):
            decisions[c.ref] = Decision("important", d.action, "sender marked as important")
    return decisions, cost, note


def headline(counts: dict[str, int]) -> str:
    total = sum(counts.values())
    if total == 0:
        return "Mail revision: nothing new"
    parts = []
    if counts.get("needs_reply"):
        n = counts["needs_reply"]
        parts.append(f"{n} need{'s' if n == 1 else ''} your reply")
    if counts.get("important"):
        parts.append(f"{counts['important']} important")
    if not parts:
        return f"Mail revision: nothing needs you ({total} new)"
    return "Mail revision: " + ", ".join(parts)


def run_pass(conn: Conn, now: datetime, llm: StructuredLlm | None, config: Config) -> int:
    since = window_start(conn, now)
    items = candidates(conn, since, now)
    decisions, cost, note = classify(conn, config, llm, items, now)
    by_class: dict[str, list[dict[str, Any]]] = {k: [] for k in CLASSES}
    for c in items:
        d = decisions[c.ref]
        by_class[d.cls].append({**c.to_dict(), "reason": d.action or d.reason, "class": d.cls})
    counts = {k: len(v) for k, v in by_class.items()}
    sections: list[Section] = []
    if note:
        sections.append(Section("Triage", note, kind="note"))
    for cls in CLASSES:
        if by_class[cls]:
            sections.append(Section(GROUP_TITLES[cls], "", by_class[cls], kind="group"))
    if not items:
        sections.append(Section("Quiet", "No new email since the previous pass.", kind="note"))
    pushed = counts["needs_reply"] + counts["important"] > 0
    row = conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode,"
        " cost_usd, push) VALUES ('revision', %s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (
            since,
            now,
            headline(counts),
            Jsonb([s.to_dict() for s in sections]),
            "ai" if cost > 0 else "data",
            round(cost, 4),
            pushed,
        ),
    ).fetchone()
    assert row is not None
    brief_id = int(row["id"])
    for c in items:
        d = decisions[c.ref]
        conn.execute(
            "INSERT INTO triage (brief_id, item_id, class, action, reason, sender)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (brief_id, c.item_id, d.cls, d.action, d.reason, c.sender),
        )
        if d.cls == "needs_reply":
            loops.open_needs_reply(conn, c.item_id, d.action or f"Reply: {c.title}", now)
    return brief_id
