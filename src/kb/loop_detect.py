"""Promise detection for open loops (open-loops spec, design D7).

For conversations that changed recently and have settled, the cheap model reads the latest
messages with the owner's marked ME and returns new promises (by the owner: i_owe; to the owner:
owed_to_me) and which open loops the conversation shows as fulfilled. Due phrases are resolved
to dates in Kyiv time by `resolve_due`. A message whose loop the owner dismissed never creates
a loop again.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parseaddr
from typing import Any
from zoneinfo import ZoneInfo

from kb import distill, loops, settings_store
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm
from kb.routines import KYIV

log = logging.getLogger(__name__)

AI_SOURCE = "_loops"
LOOKBACK = timedelta(days=14)
SETTLE = timedelta(minutes=20)
MAX_MESSAGES = 40
PER_CYCLE = 20

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["new", "fulfilled"],
    "properties": {
        "new": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "title", "counterpart", "message", "due_phrase"],
                "properties": {
                    "kind": {"type": "string", "enum": ["i_owe", "owed_to_me"]},
                    "title": {"type": "string"},
                    "counterpart": {"type": "string"},
                    "message": {"type": "string"},
                    "due_phrase": {"type": "string"},
                },
            },
        },
        "fulfilled": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["loop", "message"],
                "properties": {"loop": {"type": "string"}, "message": {"type": "string"}},
            },
        },
    },
}

PROMPT = """You track promises in the owner's conversation (email or Telegram). Messages are
numbered [m1], [m2]...; the owner's messages are marked ME, others OTHER (name).
Return in `new` only clear commitments made in these messages:
- kind "i_owe": the owner (ME) promises to do or send something ("I'll send the price list by
  Monday", "надішлю завтра", "сделаю к пятнице");
- kind "owed_to_me": someone promises the owner to do or send something.
Do NOT return: questions, requests without a promise, chit-chat ("ok, thanks"), things already
done in the same messages, vague intentions without an action.
`title`: a short imperative of what is owed, in English (e.g. "Send the November price list").
`counterpart`: the other person's name (to whom the owner owes, or who owes the owner).
`message`: the [mN] where the promise was made. `due_phrase`: the time words exactly as written
("by Monday", "завтра", "до п'ятниці") or "" if none.
In `fulfilled`, list open loops (given as [loop:N]) that a later message shows as done (the
file was sent, the answer given), with the [mN] that shows it. Return empty lists when nothing
applies."""


# --- due phrases ----------------------------------------------------------------------------

_WEEKDAYS: list[tuple[int, tuple[str, ...]]] = [
    (0, ("monday", "понеділ", "понедельн")),
    (1, ("tuesday", "вівтор", "вторник")),
    (2, ("wednesday", "серед", "сред")),
    (3, ("thursday", "четвер")),
    (4, ("friday", "п'ятниц", "п\u02bcятниц", "п\u2019ятниц", "пятниц")),
    (5, ("saturday", "субот", "суббот")),
    (6, ("sunday", "неділ", "воскресен")),
]


def resolve_due(phrase: str | None, said_at: datetime, tz: ZoneInfo = KYIV) -> date | None:
    """Date for a due phrase (en/uk/ru) relative to when it was said, in the owner's zone."""
    if not phrase or not phrase.strip():
        return None
    p = phrase.lower().strip()
    base = said_at.astimezone(tz).date()
    if m := re.search(r"(\d{4})-(\d{2})-(\d{2})", p):
        return date(int(m[1]), int(m[2]), int(m[3]))
    if m := re.search(r"\b(\d{1,2})[./](\d{1,2})(?:[./](\d{2,4}))?\b", p):
        day, month = int(m[1]), int(m[2])
        year = int(m[3]) if m[3] else base.year
        year = year + 2000 if year < 100 else year
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        return d if m[3] or d >= base else date(year + 1, month, day)
    if any(w in p for w in ("day after tomorrow", "післязавтра", "послезавтра")):
        return base + timedelta(days=2)
    if any(w in p for w in ("tomorrow", "завтра")):
        return base + timedelta(days=1)
    if any(w in p for w in ("today", "tonight", "сьогодні", "сегодня", "до вечора", "до вечера")):
        return base
    if m := re.search(r"(?:in|через)\s+(\d+)\s*(?:days?|дн|день|дня|дней)", p):
        return base + timedelta(days=int(m[1]))
    if any(w in p for w in ("end of the week", "end of week", "кінця тижня", "конца недели")):
        return base + timedelta(days=(4 - base.weekday()) % 7)
    if any(
        w in p for w in ("next week", "наступного тижня", "наступному тижні", "следующей неделе")
    ):
        return base + timedelta(days=7 - base.weekday())
    if any(w in p for w in ("end of the month", "end of month", "кінця місяця", "конца месяца")):
        nxt = (base.replace(day=28) + timedelta(days=4)).replace(day=1)
        return nxt - timedelta(days=1)
    for weekday, stems in _WEEKDAYS:
        if any(s in p for s in stems):
            return base + timedelta(days=((weekday - base.weekday()) % 7) or 7)
    return None


# --- detection ------------------------------------------------------------------------------


@dataclass
class Msg:
    tag: str
    key: str
    sent_at: datetime
    me: bool
    author: str
    body: str
    link: str | None


def _messages(conn: Conn, item: dict[str, Any], emails: set[str], tg_ids: set[str]) -> list[Msg]:
    rows = conn.execute(
        """
        SELECT message_key, sent_at, author, body, locator, kind, identity_keys FROM messages
        WHERE source_id = %s AND unit_key = %s AND NOT hidden
          AND NOT (coalesce(metadata->'labels', '[]'::jsonb) ? '\\Draft')
        ORDER BY sent_at DESC LIMIT %s
        """,
        (item["source_id"], item["source_item_key"], MAX_MESSAGES),
    ).fetchall()
    out = []
    for n, r in enumerate(reversed(rows), 1):
        if r["kind"] == "email":
            me = parseaddr(r["author"] or "")[1].lower() in emails
        else:
            me = any(k.removeprefix("tg:") in tg_ids for k in r["identity_keys"] or [])
        out.append(
            Msg(
                tag=f"m{n}",
                key=r["message_key"],
                sent_at=r["sent_at"],
                me=me,
                author=r["author"] or "unknown",
                body=(r["body"] or "")[:1500],
                link=r["locator"] if str(r["locator"] or "").startswith("https://") else None,
            )
        )
    return out


def _text(item: dict[str, Any], msgs: list[Msg], open_loops: list[dict[str, Any]]) -> str:
    lines = [f"Conversation: {item['title'] or '(no subject)'}"]
    if open_loops:
        lines.append("Open loops:")
        lines += [f"[loop:{lp['id']}] {lp['kind']}: {lp['title']}" for lp in open_loops]
    lines.append("Messages:")
    for m in msgs:
        who = "ME" if m.me else f"OTHER ({m.author})"
        lines.append(f"[{m.tag}] {m.sent_at.astimezone(KYIV):%a %d %b %H:%M} {who}: {m.body}")
    return "\n".join(lines)


def detect(
    conn: Conn, config: Config, llm: StructuredLlm, item_id: int, now: datetime
) -> dict[str, int]:
    """Runs detection for one conversation; returns counts of opened and closed loops."""
    item = conn.execute("SELECT * FROM items WHERE id = %s", (item_id,)).fetchone()
    if item is None:
        return {"opened": 0, "closed": 0}
    emails, tg_ids = loops.owner_emails(conn, config), loops.owner_telegram_ids(conn)
    msgs = _messages(conn, item, emails, tg_ids)
    by_tag = {m.tag: m for m in msgs}
    open_loops = conn.execute(
        "SELECT id, kind, title FROM loops WHERE item_id = %s AND status IN ('open', 'snoozed')",
        (item_id,),
    ).fetchall()
    model = config.llm.model()
    data, usage = llm.structured(
        model, PROMPT, _text(item, msgs, open_loops), SCHEMA, "loops", "low"
    )
    distill.record_usage(conn, AI_SOURCE, model, "loops", usage)
    opened = closed = 0
    for n in data.get("new") or []:
        m = by_tag.get(n.get("message", ""))
        if m is None or n.get("kind") not in ("i_owe", "owed_to_me") or not n.get("title"):
            continue
        if (n["kind"] == "i_owe") != m.me:
            continue  # i_owe must be the owner's message, owed_to_me someone else's
        if (
            conn.execute(
                "SELECT 1 FROM loop_dismissed_sources WHERE source_message_key = %s", (m.key,)
            ).fetchone()
            or conn.execute(
                "SELECT 1 FROM loops WHERE source_message_key = %s AND kind = %s",
                (m.key, n["kind"]),
            ).fetchone()
        ):
            continue
        row = conn.execute(
            "INSERT INTO loops (kind, title, item_id, counterpart, scopes, source_message_key,"
            " source_link, due_date, opened_at, created_at)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                n["kind"],
                str(n["title"])[:200],
                item_id,
                str(n.get("counterpart") or "")[:200],
                item["scopes"],
                m.key,
                m.link or item["locator"],
                resolve_due(n.get("due_phrase"), m.sent_at),
                m.sent_at,
                now,
            ),
        ).fetchone()
        assert row is not None
        loops._event(conn, row["id"], "opened", "system", source="detection")
        opened += 1
    live = {f"loop:{lp['id']}": lp["id"] for lp in open_loops}
    for f in data.get("fulfilled") or []:
        loop_id, m = live.get(f.get("loop", "")), by_tag.get(f.get("message", ""))
        if loop_id is None or m is None:
            continue
        conn.execute(
            "UPDATE loops SET status = 'done', closed_at = %s, closing_message_key = %s"
            " WHERE id = %s AND status IN ('open', 'snoozed')",
            (now, m.key, loop_id),
        )
        loops._event(conn, loop_id, "done", "system", closing_message_key=m.key)
        closed += 1
    return {"opened": opened, "closed": closed}


def detect_cycle(
    conn: Conn, config: Config, llm: StructuredLlm | None, now: datetime, limit: int = PER_CYCLE
) -> int:
    """Checks up to `limit` recently changed, settled conversations; returns how many."""
    if llm is None or distill.month_spend_usd(conn, now.date()) >= settings_store.budget_usd(
        conn, config
    ):
        return 0
    has_tg_owner = bool(loops.owner_telegram_ids(conn))
    kinds = ["email_thread", "tg_conversation"] if has_tg_owner else ["email_thread"]
    rows = conn.execute(
        "SELECT id, content_hash FROM items WHERE NOT hidden AND kind = ANY(%s)"
        " AND last_activity_at > %s AND last_activity_at <= %s"
        " AND content_hash IS DISTINCT FROM loops_checked"
        " ORDER BY last_activity_at DESC LIMIT %s",
        (kinds, now - LOOKBACK, now - SETTLE, limit),
    ).fetchall()
    for r in rows:
        try:
            detect(conn, config, llm, r["id"], now)
        except Exception:
            log.exception("loop detection failed for item %s", r["id"])
            continue
        conn.execute(
            "UPDATE items SET loops_checked = coalesce(content_hash, '') WHERE id = %s", (r["id"],)
        )
    return len(rows)
