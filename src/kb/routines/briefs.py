"""Briefs: rendered from a fact pack and stored as a page (design D5). This module holds the
data-only rendering, used before the AI step exists and whenever the AI budget is reached."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from psycopg.types.json import Jsonb

from kb.db import Conn
from kb.routines import RoutineName
from kb.routines.factpack import FactPack

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


@dataclass
class Section:
    title: str
    text: str
    items: list[dict[str, Any]] = field(default_factory=list)

    @property
    def refs(self) -> list[str]:
        return [i["ref"] for i in self.items]

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "text": self.text, "refs": self.refs, "items": self.items}


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


def store(conn: Conn, pack: FactPack, sections: list[Section], mode: str) -> int:
    row = conn.execute(
        "INSERT INTO briefs (routine, window_start, window_end, headline, sections, mode)"
        " VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
        (
            pack.routine,
            pack.window[0],
            pack.window[1],
            headline(pack),
            Jsonb([s.to_dict() for s in sections]),
            mode,
        ),
    ).fetchone()
    assert row is not None
    return int(row["id"])


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
        "created_at": row["created_at"].isoformat(),
    }


def latest(conn: Conn, routines: list[RoutineName]) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM briefs WHERE routine = ANY(%s) ORDER BY created_at DESC, id DESC LIMIT 1",
        (routines,),
    ).fetchone()
    return to_dict(row) if row else None


def run_morning(conn: Conn, now: datetime) -> int:
    from kb.routines import factpack

    pack = factpack.build(conn, "morning", factpack.morning_window(now))
    return store(conn, pack, data_only(pack), "data")


def runners() -> dict[RoutineName, Callable[[Conn, datetime], int]]:
    """Routines that can run today; the scheduler skips the others (they arrive in later tasks)."""
    return {"morning": run_morning}
