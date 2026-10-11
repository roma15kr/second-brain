"""Key passages ("bursts"): runs of consecutive messages by one author inside long
conversations, indexed on their own so a detail the conversation summary leaves out can still be
found. Each passage carries its conversation's title and AI question as topic, and search reports
it as its conversation (collapse) with the passage as the excerpt.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from kb import idf
from kb.db import Conn

log = logging.getLogger(__name__)

PASSAGES_VERSION = "1"
MIN_UNIT_MESSAGES = 4  # shorter conversations are fully covered by the unit itself
MIN_CHARS = 200
MIN_CHARS_WITHOUT_IDF = 400  # before rarity statistics exist
UNIT_KINDS = ("email_thread", "tg_conversation")


def bursts(msgs: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Group consecutive messages by the same author."""
    out: list[list[dict[str, Any]]] = []
    for m in msgs:
        if out and out[-1][-1]["author"] == m["author"]:
            out[-1].append(m)
        else:
            out.append([m])
    return out


def qualifies(conn: Conn, text: str, reactions: int, have_idf: bool) -> bool:
    if reactions > 0 and len(text) >= MIN_CHARS:
        return True
    if not have_idf:
        return len(text) >= MIN_CHARS_WITHOUT_IDF
    return len(text) >= MIN_CHARS and bool(idf.rare_tokens(conn, text))


def build_for_unit(conn: Conn, unit: dict[str, Any]) -> int:
    """(Re)build the passages of one unit item; returns how many it has now."""
    source_id, unit_key = unit["source_id"], unit["source_item_key"]
    msgs = conn.execute(
        """
        SELECT id, author, body, sent_at, locator, metadata FROM messages
        WHERE source_id = %s AND unit_key = %s AND NOT hidden ORDER BY sent_at, id
        """,
        (source_id, unit_key),
    ).fetchall()
    keep: list[str] = []
    if len(msgs) >= MIN_UNIT_MESSAGES:
        have_idf = idf.total_docs(conn) > 0
        for group in bursts(msgs):
            text = "\n".join(m["body"] for m in group)
            reactions = sum(int((m["metadata"] or {}).get("reactions") or 0) for m in group)
            if not qualifies(conn, text, reactions, have_idf):
                continue
            key = f"{unit_key}#p{group[0]['id']}"
            keep.append(key)
            conn.execute(
                """
                INSERT INTO items (source_id, source_item_key, kind, scopes, title, question,
                    raw_text, participants, occurred_at, last_activity_at, locator, metadata,
                    content_hash)
                VALUES (%(src)s, %(key)s, 'passage', %(scopes)s, %(title)s, %(question)s,
                    %(text)s, %(people)s, %(first)s, %(last)s, %(loc)s, %(md)s,
                    md5(%(text)s))
                ON CONFLICT (source_id, source_item_key) DO UPDATE SET
                    scopes = EXCLUDED.scopes, title = EXCLUDED.title,
                    question = EXCLUDED.question, raw_text = EXCLUDED.raw_text,
                    participants = EXCLUDED.participants,
                    last_activity_at = EXCLUDED.last_activity_at, locator = EXCLUDED.locator,
                    metadata = EXCLUDED.metadata, content_hash = EXCLUDED.content_hash,
                    hidden = false, updated_at = now()
                """,
                {
                    "src": source_id,
                    "key": key,
                    "scopes": list(unit["scopes"]),
                    "title": unit["title"],
                    "question": unit.get("question"),
                    "text": text,
                    "people": [group[0]["author"] or ""],
                    "first": group[0]["sent_at"],
                    "last": group[-1]["sent_at"],
                    "loc": group[0]["locator"],
                    "md": json.dumps({"parent_item_id": unit["id"], "unit_key": unit_key}),
                },
            )
    conn.execute(
        """
        DELETE FROM items WHERE source_id = %s AND kind = 'passage'
          AND metadata->>'unit_key' = %s AND NOT (source_item_key = ANY(%s))
        """,
        (source_id, unit_key, keep),
    )
    conn.execute(
        """
        UPDATE items SET metadata = metadata || jsonb_build_object('passages_v', %s::text)
        WHERE id = %s
        """,
        (PASSAGES_VERSION, unit["id"]),
    )
    return len(keep)


def backfill_cycle(conn: Conn, limit: int = 200) -> int:
    """Build passages for units that never had them (or an older passage version)."""
    units = conn.execute(
        """
        SELECT id, source_id, source_item_key, scopes, title, question FROM items
        WHERE NOT hidden AND kind = ANY(%s)
          AND coalesce(metadata->>'passages_v', '') <> %s
        ORDER BY last_activity_at DESC NULLS LAST LIMIT %s
        """,
        (list(UNIT_KINDS), PASSAGES_VERSION, limit),
    ).fetchall()
    for u in units:
        build_for_unit(conn, u)
    return len(units)
