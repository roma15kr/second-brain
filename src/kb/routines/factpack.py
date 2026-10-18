"""Fact packs: what a routine knows, gathered with SQL only (design D5). The AI step (later)
may only write prose about these facts and refer to them by id."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from typing import Any

from kb.db import Conn
from kb.routines import KYIV, RoutineName

EVENING_AT = time(19, 0)
UNSORTED = "unsorted"


@dataclass(frozen=True)
class ItemFact:
    id: int
    kind: str
    title: str
    summary: str
    outcome: str | None
    link: str | None
    last_activity_at: datetime
    scopes: list[str]
    participants: list[str]

    @property
    def ref(self) -> str:
        return f"item:{self.id}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "ref": self.ref,
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "summary": self.summary,
            "outcome": self.outcome,
            "link": self.link,
            "last_activity_at": self.last_activity_at.isoformat(),
            "scopes": self.scopes,
            "participants": self.participants,
        }


@dataclass
class FactPack:
    routine: RoutineName
    window: tuple[datetime, datetime]
    by_scope: dict[str, list[ItemFact]] = field(default_factory=dict)
    counts: dict[str, int] = field(default_factory=dict)
    loops: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # from loops.for_brief
    priorities: list[dict[str, Any]] = field(default_factory=list)  # accepted weekly plan

    def refs(self) -> set[str]:
        return {f.ref for items in self.by_scope.values() for f in items}


def morning_window(now: datetime) -> tuple[datetime, datetime]:
    """Since the last evening wrap slot (19:00 Kyiv) before today's morning, until now."""
    local = now.astimezone(KYIV)
    day = local.date() if local.time() >= EVENING_AT else local.date() - timedelta(days=1)
    start = datetime.combine(day, EVENING_AT, tzinfo=KYIV)
    return start, now


def evening_window(now: datetime, morning_at: time = time(8, 0)) -> tuple[datetime, datetime]:
    """Today since the morning brief slot (08:00 Kyiv), until now."""
    local = now.astimezone(KYIV)
    day = local.date() if local.time() >= morning_at else local.date() - timedelta(days=1)
    return datetime.combine(day, morning_at, tzinfo=KYIV), now


def _scope_order(scope: str) -> tuple[int, str]:
    return (1 if scope == UNSORTED else 0, scope)


def build(conn: Conn, routine: RoutineName, window: tuple[datetime, datetime]) -> FactPack:
    """Conversations (not passages) with activity in the window, grouped by scope, newest first.
    An item with several scopes appears under each."""
    rows = conn.execute(
        """
        SELECT id, kind, scopes, coalesce(title, '') AS title,
               coalesce(summary, question, left(raw_text, 300)) AS summary, outcome, locator,
               last_activity_at, participants
        FROM items
        WHERE NOT hidden
          AND kind IN ('email_thread', 'tg_conversation', 'clickup_task', 'clickup_chat')
          AND last_activity_at > %s AND last_activity_at <= %s
        ORDER BY last_activity_at DESC
        """,
        window,
    ).fetchall()
    pack = FactPack(routine=routine, window=window)
    for r in rows:
        fact = ItemFact(
            id=r["id"],
            kind=r["kind"],
            title=r["title"],
            summary=(r["summary"] or "").strip(),
            outcome=r["outcome"],
            link=r["locator"] if str(r["locator"] or "").startswith("https://") else None,
            last_activity_at=r["last_activity_at"],
            scopes=list(r["scopes"]),
            participants=list(r["participants"]),
        )
        for scope in fact.scopes or [UNSORTED]:
            pack.by_scope.setdefault(scope, []).append(fact)
        pack.counts[r["kind"]] = pack.counts.get(r["kind"], 0) + 1
    pack.by_scope = dict(sorted(pack.by_scope.items(), key=lambda kv: _scope_order(kv[0])))
    return pack
