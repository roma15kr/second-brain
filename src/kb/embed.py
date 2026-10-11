"""Local embeddings for conversation units (multilingual-e5-large via fastembed / ONNX, CPU).

What is embedded: the AI summary fields when present (question, summary, outcome, entities) plus
the title and the start of the text; before a unit is summarized, the title and start of the text.
An item is re-embedded when its content, its summary or the model changes (`embedded_key`).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from typing import Any, Protocol

from kb.config import Config, EmbeddingConfig
from kb.db import Conn

log = logging.getLogger(__name__)

UNIT_KINDS = ("email_thread", "tg_conversation")


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


_KEY_SQL = (
    "md5(coalesce(content_hash, '') || ':' || coalesce(distilled_key, '') || ':' || %(model)s)"
)


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


def run_cycle(conn: Conn, config: Config, embedder: Embedder) -> int:
    """Embed up to `per_cycle` stale items. Returns how many were embedded."""
    cfg = config.embedding
    todo = pending(conn, cfg, cfg.per_cycle)
    if not todo:
        return 0
    vecs = embedder.passages([embed_text(it, cfg.max_chars) for it in todo])
    for it, vec in zip(todo, vecs, strict=True):
        if len(vec) != cfg.dims:
            raise ValueError(f"model returned {len(vec)} dims, expected {cfg.dims}")
        conn.execute(
            "UPDATE items SET embedding = %s::vector, embedded_key = %s WHERE id = %s",
            (vector_literal(vec), it["key"], it["id"]),
        )
    return len(todo)
