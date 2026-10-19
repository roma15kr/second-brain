"""Email priority (assistant-actions spec: email priority with reasons; design D18).

Deterministic and cheap: importance from who the sender is to the owner (marked important,
how often they talk), a link to a confirmed goal (meaning match in the goal's project), money or
contract words; urgency from deadline words and how long the sender has waited. The quadrant
(do now, schedule, delegate, drop) and the reason text come from those features, never from AI.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from kb.db import Conn

GOAL_SIMILARITY = 0.83  # e5 cosine: related texts score ~0.83+, unrelated ~0.75
FREQUENT, KNOWN = 8, 3  # conversations with the sender in 90 days
QUICK_CHARS = 280  # a reply to a message this short usually takes two minutes

MONEY = re.compile(
    r"(invoice|contract|payment|price|quote|offer|договір|договор|рахун|счет|сч[её]т|оплат|"
    r"ціна|цін[уи]|цена|цен[уы]|комерційн|коммерческ)",
    re.IGNORECASE,
)
DEADLINE = re.compile(
    r"\b(urgent|asap|today|tomorrow|deadline|eod|терміново|сьогодні|завтра|дедлайн|срочно|"
    r"сегодня|до кінця дня|до конца дня)\b",
    re.IGNORECASE,
)

QUADRANTS = {
    (True, True): "do_now",
    (True, False): "schedule",
    (False, True): "delegate",
    (False, False): "drop",
}


@dataclass
class Priority:
    item_id: int
    importance: int = 0
    urgency: int = 0
    reasons: list[str] = field(default_factory=list)
    quick: bool = False
    goal_id: int | None = None

    @property
    def quadrant(self) -> str:
        return QUADRANTS[(self.importance >= 3, self.urgency >= 2)]

    @property
    def score(self) -> int:
        return (self.importance + 1) * (self.urgency + 1)

    @property
    def reason(self) -> str:
        return " · ".join(self.reasons)

    def to_dict(self) -> dict[str, Any]:
        return {
            "quadrant": self.quadrant,
            "reason": self.reason,
            "quick": self.quick,
            "score": self.score,
            "goal_id": self.goal_id,
        }


def _address(author: str | None) -> str:
    a = (author or "").strip()
    return a[a.find("<") + 1 : a.find(">")].lower() if "<" in a and ">" in a else a.lower()


def _body(text: str) -> str:
    head, sep, rest = text.partition("\n\n")
    return (rest if sep and head.startswith("From:") else text).strip()


def _goal_label(scope: str, title: str) -> str:
    return f"{scope[:1].upper()}{scope[1:]} goal: {title}"


def assess(conn: Conn, item_ids: list[int], owner: set[str], now: datetime) -> dict[int, Priority]:
    if not item_ids:
        return {}
    out = {i: Priority(i) for i in item_ids}
    goals: dict[int, dict[str, Any]] = {}
    for r in conn.execute(
        """
        SELECT DISTINCT ON (i.id) i.id, g.id AS goal_id, g.title, g.scope,
               1 - (i.embedding <=> g.embedding) AS sim
        FROM items i JOIN goals g ON g.status = 'confirmed' AND g.embedding IS NOT NULL
                                 AND g.scope = ANY(i.scopes)
        WHERE i.id = ANY(%s) AND i.embedding IS NOT NULL
        ORDER BY i.id, i.embedding <=> g.embedding
        """,
        (item_ids,),
    ).fetchall():
        if r["sim"] >= GOAL_SIMILARITY:
            goals[r["id"]] = dict(r)
    prefs = {
        r["address"]: r["pref"]
        for r in conn.execute("SELECT address, pref FROM sender_prefs").fetchall()
    }
    for item in conn.execute(
        "SELECT id, source_id, source_item_key, title, summary, entities FROM items"
        " WHERE id = ANY(%s)",
        (item_ids,),
    ).fetchall():
        p = out[item["id"]]
        last = conn.execute(
            "SELECT author, body, sent_at FROM messages WHERE source_id = %s AND unit_key = %s"
            " AND NOT hidden ORDER BY sent_at DESC LIMIT 5",
            (item["source_id"], item["source_item_key"]),
        ).fetchall()
        inbound = next((m for m in last if _address(m["author"]) not in owner), None)
        sender = _address(inbound["author"]) if inbound else ""
        if (g := goals.get(item["id"])) is not None:
            p.importance += 3
            p.goal_id = g["goal_id"]
            p.reasons.append(_goal_label(g["scope"], g["title"]))
        pref = prefs.get(sender)
        if pref == "important":
            p.importance += 3
            p.reasons.append("important sender")
        elif pref == "noise":
            p.importance -= 3
        if sender and pref != "important":
            n = _conversations_with(conn, sender, now)
            if n >= FREQUENT:
                p.importance += 2
                p.reasons.append(f"frequent contact ({n} conversations in 90 days)")
            elif n >= KNOWN:
                p.importance += 1
        body = _body(inbound["body"]) if inbound else ""
        text = " ".join([item["title"] or "", item["summary"] or "", body[:2000]])
        amounts = [e.get("value") for e in item["entities"] or [] if e.get("type") == "amount"]
        if amounts or MONEY.search(text):
            p.importance += 2
            p.reasons.append(f"money: {amounts[0]}" if amounts else "money or contract")
        if (m := DEADLINE.search(text)) is not None:
            p.urgency += 2
            p.reasons.append(f'deadline: "{m.group(0)}"')
        if inbound is not None:
            waited = now - inbound["sent_at"]
            if waited >= timedelta(days=3):
                p.urgency += 2
                p.reasons.append(f"waiting {waited.days} days")
            elif waited >= timedelta(days=1):
                p.urgency += 1
                p.reasons.append(f"waiting {waited.days} day{'s' if waited.days > 1 else ''}")
            p.quick = 0 < len(body) <= QUICK_CHARS
    return out


def _conversations_with(conn: Conn, address: str, now: datetime) -> int:
    row = conn.execute(
        "SELECT count(*) AS n FROM items WHERE identity_keys && %s AND NOT hidden"
        " AND kind IN ('email_thread', 'tg_conversation') AND last_activity_at > %s",
        ([f"email:{address}"], now - timedelta(days=90)),
    ).fetchone()
    return int(row["n"]) if row else 0


def ordered(priorities: dict[int, Priority], item_ids: list[int]) -> list[int]:
    """Highest score first; ties keep the given order."""
    rank = {i: n for n, i in enumerate(item_ids)}
    return sorted(item_ids, key=lambda i: (-priorities[i].score, rank[i]))
