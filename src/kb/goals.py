"""Goals from the owner's core documents (personal-base spec: goals from plans).

For each new version of a constitution, plan or goals document the AI may read, the AI proposes
goals with the paragraph they come from; a goal whose quote is not in the document is dropped.
Only goals the owner confirms are used for priorities and reviews.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from kb import distill, library, settings_store
from kb.config import Config
from kb.db import Conn
from kb.distill import StructuredLlm

log = logging.getLogger(__name__)

AI_SOURCE = "_library"
MAX_CHARS = 60_000

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["goals"],
    "properties": {
        "goals": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "measure", "deadline", "quote"],
                "properties": {
                    "title": {"type": "string"},
                    "measure": {"type": "string"},
                    "deadline": {"type": "string"},
                    "quote": {"type": "string"},
                },
            },
        }
    },
}

PROMPT = """You read the owner's planning document and list the concrete goals it sets (at most
10). For each goal: `title` a short outcome in English ("Launch on 2 new marketplaces");
`measure` how success is measured, if the document says ("listings live"), else "";
`deadline` as YYYY-MM-DD if the document gives a date or a quarter/month (use its last day),
else ""; `quote` a short exact quote (5-20 words, copied character for character) from the
paragraph the goal comes from. Skip values, wishes and principles that are not goals."""


def _norm(s: str) -> str:
    return " ".join(s.split()).lower()


def _paragraph(text: str, quote: str) -> str | None:
    q = _norm(quote)
    if len(q) < 10:
        return None
    for para in text.split("\n\n"):
        if q in _norm(para):
            return para.strip()[:600]
    return None


def _deadline(value: str) -> date | None:
    try:
        return date.fromisoformat(value.strip()) if value.strip() else None
    except ValueError:
        return None


def propose(conn: Conn, llm: StructuredLlm, config: Config, doc_id: int, now: datetime) -> int:
    """Proposes goals from the latest version of a core document. Returns how many."""
    doc = library.get(conn, doc_id)
    version = library.latest_version(conn, doc_id)
    if doc["kind"] not in library.CORE_KINDS or not doc["ai_allowed"] or version is None:
        return 0
    from kb.redact import redact_text

    text = redact_text(version["text"])[:MAX_CHARS]
    model = config.llm.briefs_model()
    data, usage = llm.structured(
        model, PROMPT, f"# {doc['title']}\n\n{text}", SCHEMA, "goals", "low"
    )
    distill.record_usage(conn, AI_SOURCE, model, "goals", usage)
    conn.execute(
        "DELETE FROM goals WHERE document_id = %s AND status = 'proposed'", (doc_id,)
    )  # a new version replaces earlier unconfirmed proposals
    n = 0
    for g in data.get("goals") or []:
        para = _paragraph(text, str(g.get("quote", "")))
        if para is None or not str(g.get("title", "")).strip():
            log.info("dropping goal without a verifiable quote: %s", g.get("title"))
            continue
        conn.execute(
            "INSERT INTO goals (document_id, version_id, title, scope, measure, deadline,"
            " source_excerpt) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (
                doc_id,
                version["id"],
                str(g["title"]).strip()[:200],
                doc["scopes"][0],
                str(g.get("measure", "")).strip()[:200],
                _deadline(str(g.get("deadline", ""))),
                para,
            ),
        )
        n += 1
    conn.execute(
        "UPDATE documents SET goals_version_id = %s WHERE id = %s", (version["id"], doc_id)
    )
    return n


def cycle(conn: Conn, config: Config, llm: StructuredLlm | None, now: datetime) -> int:
    """Background: core documents with a new version get goal proposals (one per cycle)."""
    if llm is None or distill.month_spend_usd(conn, now.date()) >= settings_store.budget_usd(
        conn, config
    ):
        return 0
    row = conn.execute(
        """
        SELECT d.id FROM documents d
        WHERE d.kind IN ('constitution', 'plan', 'goals') AND d.ai_allowed
          AND d.goals_version_id IS DISTINCT FROM
              (SELECT max(id) FROM document_versions v WHERE v.document_id = d.id)
        ORDER BY d.updated_at LIMIT 1
        """
    ).fetchone()
    if row is None:
        return 0
    try:
        return propose(conn, llm, config, int(row["id"]), now)
    except Exception:
        log.exception("goal proposal failed for document %s", row["id"])
        conn.execute(  # do not retry the same version in a loop
            "UPDATE documents SET goals_version_id = (SELECT max(id) FROM document_versions"
            " WHERE document_id = %s) WHERE id = %s",
            (row["id"], row["id"]),
        )
        return 0


def act(
    conn: Conn,
    goal_id: int,
    action: str,
    now: datetime,
    title: str | None = None,
    measure: str | None = None,
    deadline: date | None = None,
    scope: str | None = None,
) -> None:
    if action not in ("confirm", "remove", "edit"):
        raise ValueError("action must be confirm, remove or edit")
    if not conn.execute("SELECT 1 FROM goals WHERE id = %s", (goal_id,)).fetchone():
        raise LookupError(f"no goal {goal_id}")
    conn.execute(
        "UPDATE goals SET title = coalesce(%s, title), measure = coalesce(%s, measure),"
        " deadline = coalesce(%s, deadline), scope = coalesce(%s, scope) WHERE id = %s",
        (title, measure, deadline, scope, goal_id),
    )
    if action == "confirm":
        conn.execute(
            "UPDATE goals SET status = 'confirmed', confirmed_at = %s WHERE id = %s",
            (now, goal_id),
        )
    elif action == "remove":
        conn.execute("UPDATE goals SET status = 'removed' WHERE id = %s", (goal_id,))


def listing(conn: Conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT g.*, d.title AS document FROM goals g LEFT JOIN documents d ON d.id = g.document_id"
        " WHERE g.status <> 'removed' ORDER BY g.status = 'confirmed', g.deadline NULLS LAST, g.id"
    ).fetchall()
    return [
        {
            "id": r["id"],
            "title": r["title"],
            "scope": r["scope"],
            "measure": r["measure"],
            "deadline": r["deadline"].isoformat() if r["deadline"] else None,
            "status": r["status"],
            "document": r["document"],
            "document_id": r["document_id"],
            "source_excerpt": r["source_excerpt"],
        }
        for r in rows
    ]


def confirmed(conn: Conn) -> list[dict[str, Any]]:
    return [g for g in listing(conn) if g["status"] == "confirmed"]
