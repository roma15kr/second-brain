"""Search over items. v1 slice 1: lexical (full-text) ranking with filters."""

from __future__ import annotations

import contextlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from kb.config import SCOPES
from kb.db import Conn

VALID_SCOPES = (*SCOPES, "unsorted")
MAX_LIMIT = 50
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class SearchError(ValueError):
    pass


@dataclass
class SearchFilters:
    scopes: list[str] | None = None
    sources: list[str] | None = None
    kinds: list[str] | None = None
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


def _filter_sql(filters: SearchFilters, params: dict[str, Any]) -> list[str]:
    where = ["NOT hidden"]
    if filters.scopes:
        where.append("scopes && %(scopes)s")
        params["scopes"] = filters.scopes
    if filters.sources:
        where.append("source_id = ANY(%(sources)s)")
        params["sources"] = filters.sources
    if filters.kinds:
        where.append("kind = ANY(%(kinds)s)")
        params["kinds"] = filters.kinds
    if filters.date_from:
        where.append("last_activity_at >= %(date_from)s")
        params["date_from"] = filters.date_from
    if filters.date_to:
        where.append("occurred_at < %(date_to)s::date + 1")
        params["date_to"] = filters.date_to
    return where


def _evidence(r: dict[str, Any], excerpt: str, score: float) -> Evidence:
    return Evidence(
        item_id=r["id"],
        source=r["source_id"],
        kind=r["kind"],
        scopes=list(r["scopes"]),
        title=r["title"],
        participants=list(r["participants"]),
        occurred_at=r["occurred_at"],
        last_activity_at=r["last_activity_at"],
        excerpt=excerpt,
        locator=r["locator"],
        score=score,
        summary=r.get("summary"),
        extra={
            "message_count": (r.get("metadata") or {}).get("message_count"),
            "question": r.get("question"),
            "outcome": r.get("outcome"),
            "scope_by": (r.get("metadata") or {}).get("scope_by"),
        },
    )


def recent(conn: Conn, filters: SearchFilters | None = None, limit: int = 20) -> list[Evidence]:
    """Most recently active items, newest first."""
    filters = filters or SearchFilters()
    filters.validate()
    if not 1 <= limit <= MAX_LIMIT:
        raise SearchError(f"limit must be between 1 and {MAX_LIMIT}")
    params: dict[str, Any] = {"limit": limit}
    where = _filter_sql(filters, params)
    rows = conn.execute(
        f"""
        SELECT id, source_id, kind, scopes, title, participants, occurred_at, last_activity_at,
               locator, metadata, summary, question, outcome, right(raw_text, 400) AS tail
        FROM items WHERE {" AND ".join(where)}
        ORDER BY last_activity_at DESC NULLS LAST LIMIT %(limit)s
        """,
        params,
    ).fetchall()
    return [_evidence(r, r["tail"], 0.0) for r in rows]


RRF_K = 60
CANDIDATES = 50
_COLUMNS = """id, source_id, kind, scopes, title, participants, occurred_at, last_activity_at,
               locator, metadata, summary, question, outcome"""


def _lexical(conn: Conn, query: str, filters: SearchFilters) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"query": query, "n": CANDIDATES}
    where = [*_filter_sql(filters, params), "tsv @@ q"]
    return conn.execute(
        f"""
        SELECT {_COLUMNS}, ts_rank_cd(tsv, q) AS score,
               ts_headline('simple', raw_text, q,
                           'MaxWords=60, MinWords=20, MaxFragments=2, FragmentDelimiter=" … "')
                   AS excerpt
        FROM items, websearch_to_tsquery('simple', %(query)s) AS q
        WHERE {" AND ".join(where)}
        ORDER BY score DESC, last_activity_at DESC NULLS LAST
        LIMIT %(n)s
        """,
        params,
    ).fetchall()


def _vector(conn: Conn, qvec: list[float], filters: SearchFilters) -> list[dict[str, Any]]:
    from kb.embed import vector_literal

    # Iterative scans keep filtered HNSW queries complete (pgvector >= 0.8; ignored before).
    for setting in ("SET hnsw.ef_search = 200", "SET hnsw.iterative_scan = relaxed_order"):
        with contextlib.suppress(Exception):
            conn.execute(setting)
    params: dict[str, Any] = {"q": vector_literal(qvec), "n": CANDIDATES}
    where = [*_filter_sql(filters, params), "embedding IS NOT NULL"]
    return conn.execute(
        f"""
        SELECT {_COLUMNS}, 1 - (embedding <=> %(q)s::vector) AS score,
               coalesce(summary, left(raw_text, 300)) AS excerpt
        FROM items
        WHERE {" AND ".join(where)}
        ORDER BY embedding <=> %(q)s::vector
        LIMIT %(n)s
        """,
        params,
    ).fetchall()


def fuse(*ranked: list[dict[str, Any]], k: int = RRF_K) -> list[tuple[dict[str, Any], float]]:
    """Reciprocal rank fusion: score = sum of 1 / (k + rank) over the lists an item appears in.
    Consensus across retrievers beats a single strong vote. The first list's row (e.g. the
    lexical one, with its highlighted excerpt) is kept for items found by several."""
    scores: dict[int, float] = {}
    rows: dict[int, dict[str, Any]] = {}
    for lst in ranked:
        for rank, row in enumerate(lst, start=1):
            scores[row["id"]] = scores.get(row["id"], 0.0) + 1.0 / (k + rank)
            rows.setdefault(row["id"], row)
    order = sorted(
        scores, key=lambda i: (-scores[i], -(rows[i]["last_activity_at"] or _EPOCH).timestamp())
    )
    return [(rows[i], scores[i]) for i in order]


def search(
    conn: Conn,
    query: str,
    filters: SearchFilters | None = None,
    limit: int = 10,
    embedder: Any = None,
) -> list[Evidence]:
    """Hybrid search: full-text and (when an embedder is given) meaning-based retrieval, fused
    with reciprocal rank fusion."""
    filters = filters or SearchFilters()
    filters.validate()
    if not query.strip():
        raise SearchError("query must not be empty")
    if not 1 <= limit <= MAX_LIMIT:
        raise SearchError(f"limit must be between 1 and {MAX_LIMIT}")
    lists = [_lexical(conn, query, filters)]
    if embedder is not None:
        lists.append(_vector(conn, embedder.query(query), filters))
    return [_evidence(r, r["excerpt"], score) for r, score in fuse(*lists)[:limit]]
