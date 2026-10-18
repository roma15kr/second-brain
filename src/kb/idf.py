"""Token rarity (inverse document frequency) over visible search items."""

from __future__ import annotations

import math

from kb.connectors.base import get_state, set_state
from kb.db import Conn

MIN_RARE_IDF = 4.0  # ln(N / df): with N≈3k, a token in at most ~55 items


def refresh(conn: Conn) -> int:
    """Recompute document frequencies from the full-text index. Returns N (documents)."""
    with conn.transaction():
        conn.execute("DELETE FROM token_df")
        conn.execute(
            """
            INSERT INTO token_df (token, df)
            SELECT word, ndoc FROM ts_stat('SELECT tsv FROM items WHERE NOT hidden')
            """
        )
        row = conn.execute("SELECT count(*) AS n FROM items WHERE NOT hidden").fetchone()
        n = int(row["n"]) if row else 0
        set_state(conn, "_idf", "stats", {"n": n})
    return n


def total_docs(conn: Conn) -> int:
    return int((get_state(conn, "_idf", "stats") or {}).get("n", 0))


def rare_tokens(conn: Conn, query: str, min_idf: float = MIN_RARE_IDF) -> list[tuple[str, float]]:
    """Query tokens (as the full-text parser splits them) that are rare in the corpus."""
    n = total_docs(conn)
    if n == 0:
        return []
    # A token never seen in the corpus is as rare as it gets: count it as df = 1.
    rows = conn.execute(
        """
        SELECT q.token, coalesce(d.df, 1) AS df
        FROM unnest(tsvector_to_array(to_tsvector('simple', %s))) AS q(token)
        LEFT JOIN token_df d ON d.token = q.token
        """,
        (query,),
    ).fetchall()
    out = [(r["token"], math.log(n / max(r["df"], 1))) for r in rows]
    return sorted((t for t in out if t[1] >= min_idf), key=lambda t: -t[1])
