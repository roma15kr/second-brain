"""Changing a proposal before it is created (assistant-moderation-v1): the owner's instruction
for the AI ("shorter, assign to Kate, due Monday"), or the owner's own fields. Nothing is created
here; the changed proposal waits in Moderate."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from kb import distill, settings_store
from kb.assistant import suggestions
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm

TASK_FIELDS = ("name", "description", "assignee_name", "due_date")
TEXT_FIELDS = ("body",)

SYSTEM = """You revise a proposal the owner's assistant prepared (a ClickUp task, a comment or a
message), following the owner's INSTRUCTION exactly.
- Change only what the instruction asks for; keep everything else word for word.
- Keep the language of the original text unless the instruction asks for another.
- `assignee`: the person responsible as the owner named them (prefer the full name from TEAM),
  or the current one when unchanged.
- `due`: the due date in the words used (e.g. "Monday", "2026-11-10"), the current date when
  unchanged, or "" when the owner asks to remove it.
Return every field."""


def editable(s: dict[str, Any]) -> tuple[str, ...]:
    if s["kind"] in ("task", "delegate"):
        return TASK_FIELDS
    return (*TEXT_FIELDS, "subject") if "subject" in s["payload"] else TEXT_FIELDS


def _schema(fields: tuple[str, ...]) -> dict[str, Any]:
    names = [
        "assignee" if f == "assignee_name" else "due" if f == "due_date" else f for f in fields
    ]
    return {
        "type": "object",
        "properties": {n: {"type": "string"} for n in names},
        "required": names,
        "additionalProperties": False,
    }


def _open(conn: Conn, sid: int) -> dict[str, Any]:
    s = suggestions.get(conn, sid)
    if s["status"] != "proposed":
        raise suggestions.SuggestionError(f"suggestion {sid} is {s['status']}")
    return s


def _apply(conn: Conn, s: dict[str, Any], changes: dict[str, Any], now: datetime) -> dict[str, Any]:
    """Applies field changes; an assignee is resolved to the team / ClickUp, due words to a date."""
    from kb import recordings
    from kb.assistant import actions
    from kb.routines import KYIV

    payload = dict(s["payload"])
    for field, value in changes.items():
        if field not in editable(s) or value is None:
            continue
        value = str(value).strip()
        if field == "assignee_name":
            said = recordings._team_member(conn, value)
            who = actions.resolve_assignee(conn, said) if said else None
            payload["assignee_name"] = who[0] if who else said
            payload["assignee_emails"] = [who[1]] if who else []
        elif field == "due_date":
            payload["due_date"] = (
                recordings.resolve_due(value, now.astimezone(KYIV)) if value else None
            )
        else:
            payload[field] = value
    return payload


def _save(conn: Conn, sid: int, payload: dict[str, Any]) -> dict[str, Any]:
    conn.execute(
        "UPDATE suggestions SET payload = %s, edited = true WHERE id = %s", (Jsonb(payload), sid)
    )
    return suggestions.get(conn, sid)


def edit(conn: Conn, sid: int, fields: dict[str, Any], now: datetime) -> dict[str, Any]:
    """The owner's own wording (typed or dictated) for some fields."""
    s = _open(conn, sid)
    return _save(conn, sid, _apply(conn, s, fields, now))


def revise(
    conn: Conn,
    config: Config,
    llm: StructuredLlm | None,
    sid: int,
    instruction: str,
    now: datetime,
) -> dict[str, Any]:
    """The AI rewrites the proposal as the owner asked; the new version waits for approval."""
    from kb import team

    instruction = instruction.strip()
    if not instruction:
        raise suggestions.SuggestionError("say or type what to change")
    s = _open(conn, sid)
    if llm is None:
        raise suggestions.SuggestionError("the AI is not configured")
    if distill.month_spend_usd(conn, now.date()) >= settings_store.budget_usd(conn, config):
        raise suggestions.SuggestionError("this month's AI budget is used up: edit it yourself")
    fields = editable(s)
    current = {f: s["payload"].get(f) or "" for f in fields}
    text = (
        f"KIND: {s['kind']}\nTEAM: {', '.join(team.names(conn))}\nTODAY: {now.date().isoformat()}\n"
        f"CURRENT: {json.dumps(current, ensure_ascii=False)}\nINSTRUCTION: {instruction}"
    )
    model = config.llm.model()
    data, usage = llm.structured(model, SYSTEM, text, _schema(fields), "revise_proposal", "low")
    distill.record_usage(conn, "assistant", model, "revise_proposal", usage)
    changes = {
        ("assignee_name" if k == "assignee" else "due_date" if k == "due" else k): v
        for k, v in data.items()
    }
    # unchanged fields keep their stored form (e.g. an ISO due date is not re-parsed)
    changes = {k: v for k, v in changes.items() if str(v).strip() != str(current.get(k) or "")}
    payload = _apply(conn, s, changes, now)
    payload["revisions"] = [
        *(s["payload"].get("revisions") or []),
        {"instruction": instruction, "at": now.isoformat()},
    ]
    return _save(conn, sid, payload)
