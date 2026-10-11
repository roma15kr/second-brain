import itertools
import json
from datetime import UTC, datetime, timedelta

import pytest

from kb import idf
from kb.search import SearchFilters, collapse, exact_terms, search

T0 = datetime(2026, 9, 1, tzinfo=UTC)
_keys = itertools.count()


def add(conn, text, title="Chat", scopes=("rdim",), days=0, kind="tg_conversation", meta=None):
    row = conn.execute(
        """
        INSERT INTO items (source_id, source_item_key, kind, scopes, title, raw_text, participants,
                           occurred_at, last_activity_at, metadata)
        VALUES ('tg', %s, %s, %s, %s, %s, '{}', %s, %s, %s) RETURNING id
        """,
        (
            f"k{next(_keys)}",
            kind,
            list(scopes),
            title,
            text,
            T0 + timedelta(days=days),
            T0 + timedelta(days=days),
            json.dumps(meta or {}),
        ),
    ).fetchone()
    return row["id"]


@pytest.fixture
def corpus(conn):
    # 60 filler conversations make a token that appears once rare: ln(61/1) ≈ 4.1
    for i in range(60):
        add(conn, f"sounds good, thanks {i % 3}", days=i % 30)
    return conn


def test_idf_refresh_counts_documents(corpus):
    add(corpus, "Rozetka listing approved")
    assert idf.refresh(corpus) == 61
    toks = dict(idf.rare_tokens(corpus, "rozetka sounds"))
    assert "rozetka" in toks and "sounds" not in toks


def test_rare_word_finds_item_when_other_words_missing(corpus):
    target = add(corpus, "Rozetka listing approved for spring")
    idf.refresh(corpus)
    # full-text alone needs every word; with rare-term scoring switched off nothing is found
    assert search(corpus, "rozetka banana", min_idf=99.0) == []
    assert search(corpus, "rozetka banana")[0].item_id == target


def test_short_filler_does_not_rank(corpus):
    target = add(corpus, "ok, kerberos keytab rotated")
    idf.refresh(corpus)
    hits = search(corpus, "kerberos sounds good")
    assert hits and hits[0].item_id == target


@pytest.mark.parametrize(
    "query, expected",
    [
        ("mail from oleh@quokka.ua about prices", ["oleh@quokka.ua"]),
        ('find "spring campaign brief"', ["spring campaign brief"]),
        ("order 4471 status", ["4471"]),
        ("why ERR_TOKEN_EXPIRED again", ["ERR_TOKEN_EXPIRED"]),
        ("renewal of rdim.ua", ["rdim.ua"]),
        ("what did we decide about ads", []),
    ],
)
def test_exact_terms(query, expected):
    assert exact_terms(query) == expected


def test_exact_email_and_id_pinned_first(corpus):
    older = add(corpus, "Price list from oleh@quokka.ua attached", days=1)
    newer_noise = add(corpus, "prices prices prices oleh quokka prices", days=29)
    order = add(corpus, "Invoice 4471 paid", days=2)
    idf.refresh(corpus)
    hits = search(corpus, "oleh@quokka.ua prices")
    assert hits[0].item_id == older and hits[0].extra["exact_match"] is True
    assert newer_noise in [h.item_id for h in hits]
    assert search(corpus, "order 4471")[0].item_id == order


def test_exact_string_ranks_first_and_respects_filters(corpus):
    target = add(corpus, "Got ERR_TOKEN_EXPIRED 0x8F2 from the API", scopes=("quokka",))
    idf.refresh(corpus)
    assert search(corpus, "ERR_TOKEN_EXPIRED")[0].item_id == target
    assert all(
        h.item_id != target
        for h in search(corpus, "ERR_TOKEN_EXPIRED", SearchFilters(scopes=["rdim"]))
    )


def test_collapse_passage_into_unit():
    unit = {"id": 1, "metadata": {}}
    passage = {"id": 2, "metadata": {"parent_item_id": 1}}
    other = {"id": 3, "metadata": {}}
    assert [r["id"] for r, _ in collapse([(passage, 0.9), (unit, 0.8), (other, 0.5)])] == [2, 3]


def test_unseen_tokens_count_as_rare(corpus):
    idf.refresh(corpus)
    toks = dict(idf.rare_tokens(corpus, "zyxwvut sounds"))
    assert "zyxwvut" in toks and "sounds" not in toks
