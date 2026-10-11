import math
import os
import zlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from kb import distill, embed, indexer
from kb.config import Config, EmbeddingConfig, LlmConfig, TelegramChat, TelegramSource
from kb.connectors import telegram
from kb.search import SearchFilters, fuse, search

T0 = datetime(2026, 9, 1, 10, tzinfo=UTC)
CHAT = telegram.ChatInfo(chat_id=-1001, title="Team", username=None, peer_type="channel")


class TrigramEmbedder:
    """Deterministic stand-in: character trigrams hashed into 1024 dims (finds word variants)."""

    dims = 1024

    def _vec(self, text):
        v = [0.0] * self.dims
        t = f"  {text.lower()}  "
        for i in range(len(t) - 2):
            v[zlib.crc32(t[i : i + 3].encode()) % self.dims] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]

    def passages(self, texts):
        return [self._vec(t) for t in texts]

    def query(self, text):
        return self._vec(text)


def make(conn, texts, scopes=None):
    src = TelegramSource(
        id="tg", type="telegram", chats=[TelegramChat(chat=-1001, scopes=scopes or ["rdim"])]
    )
    cfg = Config(sources=[src], embedding=EmbeddingConfig(cache_dir="/nonexistent"))
    for i, text in enumerate(texts):
        msg = SimpleNamespace(
            id=i + 1,
            date=T0 + timedelta(hours=3 * i),
            message=text,
            edit_date=None,
            sender=None,
            sender_id=7,
            reply_to=None,
            reactions=None,
            media=None,
        )
        telegram.on_message(conn, src, CHAT, msg)
    while indexer.run_once(conn, cfg):
        pass
    return cfg


def test_embedding_cycle_fills_and_is_idempotent(conn):
    cfg = make(conn, ["printing invoice attached", "lunch tomorrow"])
    e = TrigramEmbedder()
    assert embed.run_cycle(conn, cfg, e) == 2
    assert embed.run_cycle(conn, cfg, e) == 0
    row = conn.execute("SELECT count(*) AS n FROM items WHERE embedding IS NOT NULL").fetchone()
    assert row["n"] == 2


def test_summary_change_triggers_reembedding(conn):
    cfg = make(conn, ["Обговорили бюджет кампанії на маркетплейсі " * 3])
    e = TrigramEmbedder()
    embed.run_cycle(conn, cfg, e)
    from tests.test_distill import StubClient

    cfg.llm = LlmConfig(enabled=True)
    distill.run_cycle(conn, cfg, StubClient(), now=T0 + timedelta(days=1))
    assert embed.run_cycle(conn, cfg, e) == 1  # summary is part of the embedded text


def test_vector_finds_word_variant_that_lexical_misses(conn):
    cfg = make(conn, ["printing house sent the invoice for business cards", "lunch on friday"])
    e = TrigramEmbedder()
    embed.run_cycle(conn, cfg, e)
    assert search(conn, "invoices printing") == []  # 'simple' full-text: no stemming
    hits = search(conn, "invoices printing", embedder=e, limit=1)
    assert "invoice" in hits[0].excerpt


def test_filters_apply_to_vector_results(conn):
    cfg = make(conn, ["printing invoice attached"], scopes=["rdim"])
    e = TrigramEmbedder()
    embed.run_cycle(conn, cfg, e)
    assert search(conn, "invoices", SearchFilters(scopes=["quokka"]), embedder=e) == []
    assert search(conn, "invoices", SearchFilters(scopes=["rdim"]), embedder=e)


def test_rrf_consensus_beats_single_top():
    t = T0

    def row(i):
        return {"id": i, "last_activity_at": t}

    lexical = [row(1), row(2), row(3)]
    vector = [row(9), row(3), row(2)]
    order = [r["id"] for r, _ in fuse(lexical, vector)]
    # 3 and 2 appear in both lists; 1 and 9 are each first in only one list.
    assert order[:2] == [2, 3] or order[:2] == [3, 2]
    assert set(order[2:]) == {1, 9}


MODEL_CACHE = os.environ.get(
    "KB_MODEL_CACHE",
    "/tmp/claude-1000/-home-coder-second-brain/5c36cae3-04fa-459c-8a8b-9e3c5da8e065/scratchpad/models",
)


@pytest.mark.slow
@pytest.mark.skipif(not Path(MODEL_CACHE).exists(), reason="embedding model not downloaded")
def test_cross_language_fixture_top10(conn):
    cfg = make(
        conn,
        [
            "Друкарня надіслала рахунок за візитки, оплатити до пʼятниці.",
            "Сервер в Германии, где CRM, упал, цены обновим через час.",
            "Lunch on Friday at noon?",
            "Погодили бюджет кампанії на маркетплейсі 5000 грн, старт в понеділок.",
        ],
    )
    e = embed.FastEmbedder(EmbeddingConfig(cache_dir=MODEL_CACHE))
    embed.run_cycle(conn, cfg, e)
    hits = search(conn, "invoice from the printing house", embedder=e, limit=10)
    assert "Друкарня" in (hits[0].excerpt or "")
    hits = search(conn, "когда запускаем рекламу", embedder=e, limit=10)
    assert "маркетплейсі" in (hits[0].excerpt or "")
