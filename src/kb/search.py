"""Search over items. v1 slice 1: lexical (full-text) ranking with filters."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Any

from kb.config import SCOPES
from kb.db import Conn

VALID_SCOPES = (*SCOPES, "unsorted")
MAX_LIMIT = 50


class SearchError(ValueError):
    pass


@dataclass
class SearchFilters:
    scopes: list[str] | None = None
    sources: list[str] | None = None
    date_from: date | None = None
    date_to: date | None = None

    def validate(self) -> None:
        for s in self.scopes or []:
            if s not in VALID_SCOPES:
                raise SearchError(f"unknown scope {s!r}; valid scopes: {', '.join(VALID_SCOPES)}")


@dataclass
class Evidence:
    item_id: int
    source: str
    kind: str
    scopes: list[str]
    title: str | None
    participants: list[str]
    occurred_at: datetime | None
    last_activity_at: datetime | None
    excerpt: str
    locator: str | None
    score: float
    summary: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        for k in ("occurred_at", "last_activity_at"):
            if d[k] is not None:
                d[k] = d[k].isoformat()
        return d


def search(
    conn: Conn, query: str, filters: SearchFilters | None = None, limit: int = 10
) -> list[Evidence]:
    filters = filters or SearchFilters()
    filters.validate()
    if not query.strip():
        raise SearchError("query must not be empty")
    if not 1 <= limit <= MAX_LIMIT:
        raise SearchError(f"limit must be between 1 and {MAX_LIMIT}")

    where = ["NOT hidden", "tsv @@ q"]
    params: dict[str, Any] = {"query": query, "limit": limit}
    if filters.scopes:
        where.append("scopes && %(scopes)s")
        params["scopes"] = filters.scopes
    if filters.sources:
        where.append("source_id = ANY(%(sources)s)")
        params["sources"] = filters.sources
    if filters.date_from:
        where.append("last_activity_at >= %(date_from)s")
        params["date_from"] = filters.date_from
    if filters.date_to:
        where.append("occurred_at < %(date_to)s::date + 1")
        params["date_to"] = filters.date_to

    rows = conn.execute(
        f"""
        SELECT id, source_id, kind, scopes, title, participants, occurred_at, last_activity_at,
               locator, ts_rank_cd(tsv, q) AS score,
               ts_headline('simple', raw_text, q,
                           'MaxWords=60, MinWords=20, MaxFragments=2, FragmentDelimiter=" … "')
                   AS excerpt
        FROM items, websearch_to_tsquery('simple', %(query)s) AS q
        WHERE {" AND ".join(where)}
        ORDER BY score DESC, last_activity_at DESC NULLS LAST
        LIMIT %(limit)s
        """,
        params,
    ).fetchall()
    return [
        Evidence(
            item_id=r["id"],
            source=r["source_id"],
            kind=r["kind"],
            scopes=list(r["scopes"]),
            title=r["title"],
            participants=list(r["participants"]),
            occurred_at=r["occurred_at"],
            last_activity_at=r["last_activity_at"],
            excerpt=r["excerpt"],
            locator=r["locator"],
            score=float(r["score"]),
        )
        for r in rows
    ]
