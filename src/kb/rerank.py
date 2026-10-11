"""Local multilingual cross-encoder that rescores the top fused candidates against the query."""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Any, Protocol

from kb.config import Config

log = logging.getLogger(__name__)


class Reranker(Protocol):
    def scores(self, query: str, docs: Sequence[str]) -> list[float]: ...


class FastReranker:
    def __init__(self, model: str, cache_dir: str) -> None:
        self.model_name, self.cache_dir = model, cache_dir
        self._model: Any = None
        self._lock = threading.Lock()

    def _get(self) -> Any:
        with self._lock:
            if self._model is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                log.info("loading reranker %s", self.model_name)
                self._model = TextCrossEncoder(self.model_name, cache_dir=self.cache_dir)
            return self._model

    def preload(self) -> None:
        threading.Thread(target=self._get, daemon=True).start()

    def ready(self) -> bool:
        return self._model is not None

    def scores(self, query: str, docs: Sequence[str]) -> list[float]:
        return [float(s) for s in self._get().rerank(query, list(docs))]


def default_reranker(config: Config) -> Reranker | None:
    if not config.search.rerank:
        return None
    return FastReranker(config.search.rerank_model, config.embedding.cache_dir)


_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="rerank")


def scores_within(
    reranker: Reranker, query: str, docs: Sequence[str], budget: float
) -> list[float] | None:
    """Relevance in 0..1 per doc, or None when the reranker is not ready or too slow."""
    if not docs:
        return []
    if isinstance(reranker, FastReranker) and not reranker.ready():
        reranker.preload()
        return None  # still loading: don't make the user wait for a cold model
    future = _pool.submit(reranker.scores, query, docs)
    try:
        raw = future.result(timeout=budget)
    except FutureTimeout:
        log.warning("rerank exceeded %.1fs budget; using fused order", budget)
        return None
    except Exception:
        log.exception("rerank failed; using fused order")
        return None
    return [1 / (1 + math.exp(-s)) for s in raw]
