"""Local embeddings for conversation units (multilingual-e5-large via fastembed / ONNX, CPU).

What is embedded: the AI summary fields when present (question, summary, outcome, entities) plus
the title and the start of the text; before a unit is summarized, the title and start of the text.
An item is re-embedded when its content, its summary or the model changes (`embedded_key`).
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Sequence
from typing import Any, Protocol

from kb.config import Config, EmbeddingConfig
from kb.db import Conn

log = logging.getLogger(__name__)

UNIT_KINDS = (
    "email_thread",
    "tg_conversation",
    "passage",
    "document",
    "doc_section",
    "clickup_task",
    "clickup_comments",
    "clickup_chat",
)


class Embedder(Protocol):
    dims: int

    def passages(self, texts: Sequence[str]) -> list[list[float]]: ...
    def query(self, text: str) -> list[float]: ...


class FastEmbedder:
    """Loads the model lazily (first use) or in the background (`preload`)."""

    def __init__(self, cfg: EmbeddingConfig) -> None:
        self.cfg = cfg
        self.dims = cfg.dims
        self._model: Any = None
        self._lock = threading.Lock()

    def _get(self) -> Any:
        with self._lock:
            if self._model is None:
                from fastembed import TextEmbedding

                log.info("loading embedding model %s", self.cfg.model)
                self._model = TextEmbedding(self.cfg.model, cache_dir=self.cfg.cache_dir)
            return self._model

    def preload(self) -> None:
        threading.Thread(target=self._get, daemon=True).start()

    def passages(self, texts: Sequence[str]) -> list[list[float]]:
        # fastembed does not add model-specific prefixes; e5 needs them.
        prefixed = [self.cfg.passage_prefix + t for t in texts]
        vecs = self._get().embed(prefixed, batch_size=self.cfg.batch)
        return [v.tolist() for v in vecs]

    def query(self, text: str) -> list[float]:
        vec = next(iter(self._get().embed([self.cfg.query_prefix + text])))
        return [float(x) for x in vec]


def default_embedder(config: Config) -> Embedder | None:
    return FastEmbedder(config.embedding) if config.embedding.enabled else None


def vector_literal(vec: Sequence[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"


def embed_text(item: dict[str, Any], max_chars: int) -> str:
    parts = [item.get("title") or ""]
    for field in ("question", "summary", "outcome"):
        if item.get(field):
            parts.append(str(item[field]))
    entities = item.get("entities") or []
    if entities:
        parts.append(", ".join(str(e.get("value", "")) for e in entities if isinstance(e, dict)))
    head = "\n".join(p for p in parts if p)
    room = max(max_chars - len(head), 200)
    return f"{head}\n{item['raw_text'][:room]}"[:max_chars]


def key_sql(alias: str = "") -> str:
    """SQL for an item's embedding key: content + summary + model (`%(model)s` bound)."""
    a = f"{alias}." if alias else ""
    return (
        f"md5(coalesce({a}content_hash, '') || ':' || coalesce({a}distilled_key, '') "
        f"|| ':' || %(model)s)"
    )


_KEY_SQL = key_sql()


def pending(conn: Conn, cfg: EmbeddingConfig, limit: int) -> list[dict[str, Any]]:
    return conn.execute(
        f"""
        SELECT id, title, raw_text, question, summary, outcome, entities, {_KEY_SQL} AS key
        FROM items
        WHERE NOT hidden AND kind = ANY(%(kinds)s)
          AND embedded_key IS DISTINCT FROM {_KEY_SQL}
        ORDER BY last_activity_at DESC NULLS LAST
        LIMIT %(limit)s
        """,
        {"kinds": list(UNIT_KINDS), "model": cfg.model, "limit": limit},
    ).fetchall()


def reuse_cached(conn: Conn, cfg: EmbeddingConfig) -> int:
    """Copy cached vectors to items whose current key was embedded before (e.g. after a
    rebuild). Returns how many items were filled."""
    k = key_sql("i")
    rows = conn.execute(
        f"""
        UPDATE items i SET embedding = c.embedding, embedded_key = c.key
        FROM embedding_cache c
        WHERE NOT i.hidden AND i.kind = ANY(%(kinds)s)
          AND i.embedded_key IS DISTINCT FROM {k} AND c.key = {k}
        RETURNING i.id
        """,
        {"kinds": list(UNIT_KINDS), "model": cfg.model},
    ).fetchall()
    return len(rows)


def _valid(vec: Sequence[float], dims: int) -> bool:
    return len(vec) == dims and all(math.isfinite(x) for x in vec)


def run_cycle(conn: Conn, config: Config, embedder: Embedder) -> int:
    """Embed up to `per_cycle` stale items. A failing batch is retried item by item; an item that
    still fails is parked (embedded_key set, no vector) with its error recorded, so one bad item
    never blocks the rest. Returns how many items were processed (embedded or parked)."""
    from kb import health

    cfg = config.embedding
    reused = reuse_cached(conn, cfg)
    todo = pending(conn, cfg, cfg.per_cycle)
    if not todo:
        return reused
    texts = [embed_text(it, cfg.max_chars) for it in todo]
    try:
        vecs: list[list[float] | None] = list(embedder.passages(texts))
    except Exception:
        log.exception("embedding batch failed; retrying items one by one")
        vecs = []
        for t in texts:
            try:
                vecs.append(embedder.passages([t])[0])
            except Exception as exc:
                log.warning("embedding failed: %s", exc)
                vecs.append(None)
    done = 0
    for it, vec in zip(todo, vecs, strict=True):
        if vec is not None and _valid(vec, cfg.dims):
            lit = vector_literal(vec)
            conn.execute(
                "UPDATE items SET embedding = %s::vector, embedded_key = %s WHERE id = %s",
                (lit, it["key"], it["id"]),
            )
            conn.execute(
                "INSERT INTO embedding_cache (key, embedding) VALUES (%s, %s::vector) "
                "ON CONFLICT DO NOTHING",
                (it["key"], lit),
            )
            done += 1
        else:
            problem = "no vector" if vec is None else f"invalid vector (len {len(vec)})"
            conn.execute(
                "UPDATE items SET embedding = NULL, embedded_key = %s WHERE id = %s",
                (it["key"], it["id"]),
            )
            health.record_error(conn, "_embeddings", f"item {it['id']}: {problem}")
    if done:
        health.record_ok(conn, "_embeddings", last_batch=done)
    return len(todo)
