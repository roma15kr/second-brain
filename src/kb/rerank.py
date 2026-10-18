"""Local multilingual cross-encoder that rescores the top fused candidates against the query."""

from __future__ import annotations

import contextlib
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
        self._loading = False
        self.load_error: str | None = None
        self.last_ms: float | None = None

    def _get(self) -> Any:
        with self._lock:
            if self._model is None:
                from fastembed.rerank.cross_encoder import TextCrossEncoder

                log.info("loading reranker %s", self.model_name)
                try:
                    self._model = TextCrossEncoder(self.model_name, cache_dir=self.cache_dir)
                    self.load_error = None
                except Exception as exc:
                    self.load_error = f"{type(exc).__name__}: {exc}"[:500]
                    log.exception("reranker failed to load")
                    raise
                finally:
                    self._loading = False
            return self._model

    def preload(self) -> None:
        if self._model is not None or self._loading:
            return
        self._loading = True

        def load() -> None:
            with contextlib.suppress(Exception):  # recorded in load_error
                self._get()

        threading.Thread(target=load, daemon=True).start()

    def ready(self) -> bool:
        return self._model is not None

    def state(self) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "ready": self.ready(),
            "loading": self._loading,
            "load_error": self.load_error,
            "last_rerank_ms": self.last_ms,
        }

    def scores(self, query: str, docs: Sequence[str]) -> list[float]:
        import time

        t = time.perf_counter()
        out = [float(s) for s in self._get().rerank(query, list(docs))]
        self.last_ms = round((time.perf_counter() - t) * 1000, 1)
        return out


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
