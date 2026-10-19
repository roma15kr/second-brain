"""Reply drafts (assistant-actions spec: reply drafts; design D19).

For the top needs-reply emails of the day (owner's cap, default 5) and for every "Draft reply"
the owner taps, the briefs model writes a reply in the thread's language and the owner's tone
(learned from the owner's earlier replies to the same person, else in the same project), using
knowledge-base context. It may cite only the items it was given; other refs are dropped. Drafts
wait in the approval queue (suggestions); nothing is saved or sent here.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from kb import distill, loops, settings_store
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm

log = logging.getLogger(__name__)

AI_SOURCE = "assistant"
THREAD_MESSAGES = 6
TONE_EXAMPLES = 6
CONTEXT_ITEMS = 5
CHARS = 2000

SYSTEM = """You draft email replies for the owner of a personal knowledge base.
- Write the reply the owner would send to the LAST message of the thread, in the language of the
  thread (Ukrainian, Russian or English), matching the owner's tone in the examples (greeting,
  length, formality, sign-off).
- Use facts only from the thread and the context items; never invent prices, dates or promises.
  If something needed is unknown, write a short placeholder in square brackets, e.g. [date].
- `refs`: the context items you used, exactly as written (e.g. "item:123"); empty if none.
- Body only: no subject line, no quoted thread."""

SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "body": {"type": "string"},
        "refs": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["body", "refs"],
    "additionalProperties": False,
}

Searcher = Callable[[dict[str, Any]], list[dict[str, Any]]]


def _body(text: str) -> str:
    """Message bodies start with indexing headers (From/To/Attachments); drop them."""
    head, sep, rest = text.partition("\n\n")
    return (rest if sep and head.startswith("From:") else text).strip()


def _address(author: str | None) -> str:
    a = (author or "").strip()
    return a[a.find("<") + 1 : a.find(">")].lower() if "<" in a and ">" in a else a.lower()


def build_prompt(
    conn: Conn, item_id: int, owner: set[str], searcher: Searcher | None
) -> tuple[str, set[str]]:
    """The model input and the refs it may cite."""
    item = conn.execute("SELECT * FROM items WHERE id = %s", (item_id,)).fetchone()
    if item is None or item["kind"] != "email_thread":
        raise ValueError(f"item {item_id} is not an email thread")
    msgs = conn.execute(
        "SELECT author, sent_at, body, subject FROM messages WHERE source_id = %s"
        " AND unit_key = %s AND kind = 'email' AND NOT hidden AND "
        + loops.NOT_DRAFT.replace("m.", "")
        + " ORDER BY sent_at DESC LIMIT %s",
        (item["source_id"], item["source_item_key"], THREAD_MESSAGES),
    ).fetchall()
    msgs.reverse()
    counterpart = next(
        (_address(m["author"]) for m in reversed(msgs) if _address(m["author"]) not in owner), ""
    )
    thread = "\n\n".join(
        f"[{m['sent_at']:%Y-%m-%d %H:%M}] {m['author']}:\n{_body(m['body'])[:CHARS]}" for m in msgs
    )
    tone = _tone_examples(conn, owner, counterpart, list(item["scopes"]))
    allowed: set[str] = set()
    context = []
    for r in _context(conn, item, msgs, counterpart, searcher):
        ref = f"item:{r['item_id']}"
        allowed.add(ref)
        context.append(
            f"{ref} {r.get('title') or ''}\n{(r.get('summary') or r.get('excerpt') or '')[:600]}"
        )
    text = (
        f"THREAD: {item['title'] or ''}\n{thread}\n\n"
        f"OWNER'S EARLIER REPLIES (tone examples):\n{tone or '(none)'}\n\n"
        f"CONTEXT ITEMS:\n{chr(10).join(context) or '(none)'}"
    )
    return text, allowed


def _tone_examples(conn: Conn, owner: set[str], counterpart: str, scopes: list[str]) -> str:
    if not owner:
        return ""
    rows = conn.execute(
        """
        SELECT body, %(cp)s <> '' AND EXISTS (
                   SELECT 1 FROM unnest(participants) p WHERE lower(p) LIKE '%%' || %(cp)s || '%%'
               ) AS same_person
        FROM messages m
        WHERE kind = 'email' AND NOT hidden AND """
        + loops.NOT_DRAFT
        + """
          AND EXISTS (SELECT 1 FROM unnest(%(owner)s::text[]) o
                      WHERE lower(m.author) LIKE '%%' || o || '%%')
          AND (scopes && %(scopes)s OR %(cp)s <> '')
        ORDER BY 2 DESC, sent_at DESC LIMIT %(n)s
        """,
        {"cp": counterpart, "owner": sorted(owner), "scopes": scopes, "n": TONE_EXAMPLES},
    ).fetchall()
    return "\n---\n".join(_body(r["body"])[:600] for r in rows)


def _context(
    conn: Conn,
    item: dict[str, Any],
    msgs: list[dict[str, Any]],
    counterpart: str,
    searcher: Searcher | None,
) -> list[dict[str, Any]]:
    if searcher is not None:
        last = _body(msgs[-1]["body"])[:300] if msgs else ""
        try:
            hits = searcher(
                {
                    "query": f"{item['title'] or ''} {last}".strip(),
                    "limit": CONTEXT_ITEMS + 1,
                    "include_private": False,
                }
            )
            return [h for h in hits if h["item_id"] != item["id"]][:CONTEXT_ITEMS]
        except Exception:
            log.exception("search for reply context failed; using the person's history")
    if not counterpart:
        return []
    rows = conn.execute(
        "SELECT id AS item_id, title, summary FROM items WHERE id <> %s AND NOT hidden"
        " AND kind <> 'passage' AND NOT coalesce((metadata->>'private')::boolean, false)"
        " AND identity_keys && %s ORDER BY last_activity_at DESC NULLS LAST LIMIT %s",
        (item["id"], [f"email:{counterpart}"], CONTEXT_ITEMS),
    ).fetchall()
    return [dict(r) for r in rows]


def draft(
    conn: Conn,
    config: Config,
    llm: StructuredLlm,
    item_id: int,
    now: datetime,
    searcher: Searcher | None = None,
) -> tuple[str, list[str]]:
    owner = loops.owner_emails(conn, config)
    text, allowed = build_prompt(conn, item_id, owner, searcher)
    model = config.llm.briefs_model()
    data, usage = llm.structured(model, SYSTEM, text, SCHEMA, "reply_draft", "low")
    distill.record_usage(conn, AI_SOURCE, model, "reply_draft", usage)
    refs = [r for r in data.get("refs", []) if r in allowed]
    return str(data.get("body") or "").strip(), refs


def _within_budget(conn: Conn, config: Config, now: datetime) -> bool:
    return distill.month_spend_usd(conn, now.date()) < settings_store.budget_usd(conn, config)


def drafted_today(conn: Conn, now: datetime) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM suggestions WHERE kind = 'reply_email'"
        " AND payload->>'drafted_on' = %s",
        (loops.kyiv_today(now).isoformat(),),
    ).fetchone()
    return int(row["n"]) if row else 0


def candidates(conn: Conn, config: Config, now: datetime, limit: int) -> list[dict[str, Any]]:
    """Open needs-reply emails without a reply suggestion (and not discarded since the loop
    opened), highest priority first."""
    from kb.assistant import priority

    rows = [
        dict(r)
        for r in conn.execute(
            """
            SELECT l.item_id, l.opened_at FROM loops l JOIN items i ON i.id = l.item_id
            WHERE l.kind = 'needs_reply' AND l.status = 'open' AND i.kind = 'email_thread'
              AND NOT EXISTS (SELECT 1 FROM suggestions s WHERE s.kind = 'reply_email'
                              AND s.item_id = l.item_id
                              AND s.status IN ('proposed', 'approved', 'applying', 'applied'))
              AND NOT EXISTS (SELECT 1 FROM suggestions s WHERE s.kind = 'reply_email'
                              AND s.item_id = l.item_id AND s.status = 'discarded'
                              AND s.decided_at > l.opened_at)
            ORDER BY l.opened_at
            LIMIT 50
            """
        ).fetchall()
    ]
    ids = [r["item_id"] for r in rows]
    prio = priority.assess(conn, ids, loops.owner_emails(conn, config), now)
    by_id = {r["item_id"]: r | {"reason": prio[r["item_id"]].reason} for r in rows}
    return [by_id[i] for i in priority.ordered(prio, ids)][:limit]


def cycle(
    conn: Conn,
    config: Config,
    llm: StructuredLlm | None,
    now: datetime,
    searcher: Searcher | None = None,
) -> int:
    """One routines cycle: fill drafts the owner asked for, then at most one automatic draft
    (the daily cap spreads them over the day's revision passes)."""
    if llm is None or not _within_budget(conn, config, now):
        return 0
    done = 0
    for s in conn.execute(
        "SELECT id, item_id FROM suggestions WHERE kind = 'reply_email' AND status = 'proposed'"
        " AND (payload->>'ai_pending')::boolean ORDER BY created_at LIMIT 2"
    ).fetchall():
        done += _fill(conn, config, llm, s["id"], s["item_id"], now, searcher)
    cap = settings_store.load(conn).reply_drafts_per_day
    if drafted_today(conn, now) < cap:
        for c in candidates(conn, config, now, 1):
            from kb.assistant import suggestions

            sid = suggestions.propose(
                conn,
                "reply_email",
                {
                    "item_id": c["item_id"],
                    "body": "",
                    "auto": True,
                    "ai_pending": True,
                    "drafted_on": loops.kyiv_today(now).isoformat(),
                },
                reason=f"Needs your reply · {c['reason']}" if c["reason"] else "Needs your reply",
                refs=[f"item:{c['item_id']}"],
                item_id=c["item_id"],
                scopes=_scopes(conn, c["item_id"]),
            )
            done += _fill(conn, config, llm, sid, c["item_id"], now, searcher)
    return done


def _scopes(conn: Conn, item_id: int) -> list[str]:
    row = conn.execute("SELECT scopes FROM items WHERE id = %s", (item_id,)).fetchone()
    return list(row["scopes"]) if row else []


def _fill(
    conn: Conn,
    config: Config,
    llm: StructuredLlm,
    sid: int,
    item_id: int,
    now: datetime,
    searcher: Searcher | None,
) -> int:
    try:
        body, refs = draft(conn, config, llm, item_id, now, searcher)
    except Exception as e:
        log.exception("reply draft %s failed", sid)
        conn.execute(
            "UPDATE suggestions SET payload = payload || %s WHERE id = %s",
            (Jsonb({"ai_pending": False, "ai_error": str(e)[:200]}), sid),
        )
        return 0
    # the owner may have started writing meanwhile: never overwrite their text
    conn.execute(
        "UPDATE suggestions SET payload = payload || %s,"
        " refs = (SELECT array_agg(DISTINCT r) FROM unnest(refs || %s::text[]) r)"
        " WHERE id = %s AND status = 'proposed' AND coalesce(payload->>'body', '') = ''",
        (Jsonb({"body": body}), refs, sid),
    )
    conn.execute(
        "UPDATE suggestions SET payload = payload || '{\"ai_pending\": false}' WHERE id = %s",
        (sid,),
    )
    return 1
