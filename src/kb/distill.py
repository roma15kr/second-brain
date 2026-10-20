"""AI enrichment of conversation units (email threads, Telegram conversations).

For each settled unit (quiet for `settle_minutes`), an LLM returns: the question the conversation
answers, a short summary, the outcome, entities, the language, and a scope guess. Only redacted
text is sent. Results are cached by (content hash, model, prompt version), so rebuilds never pay
twice. Big backlogs go through the provider's Batch API; a per-source daily token cap stops new
requests.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any, Protocol

from kb.config import SCOPES, Config, LlmConfig
from kb.db import Conn

log = logging.getLogger(__name__)

PROMPT_VERSION = "1"
UNIT_KINDS = ("email_thread", "tg_conversation", "clickup_task", "clickup_chat")
# USD per 1M tokens (input, output), standard tier; Batch API is half.
PRICES = {"gpt-6-luna": (0.10, 0.50), "gpt-6.1-sol": (2.00, 10.00), "gpt-5.6-luna": (0.20, 1.20)}
CHARS_PER_TOKEN_DEFAULT = 3.0  # mixed uk/ru/en; refined from recorded usage

SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "question",
        "summary",
        "outcome",
        "entities",
        "language",
        "scope_guess",
        "scope_confidence",
    ],
    "properties": {
        "question": {"type": "string"},
        "summary": {"type": "string"},
        "outcome": {"type": ["string", "null"]},
        "entities": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "value"],
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "person",
                            "company",
                            "product",
                            "amount",
                            "date",
                            "place",
                            "other",
                        ],
                    },
                    "value": {"type": "string"},
                },
            },
        },
        "language": {"type": "string", "enum": ["uk", "ru", "en", "mixed", "other"]},
        "scope_guess": {"type": "string", "enum": [*SCOPES, "unknown"]},
        "scope_confidence": {"type": "number"},
    },
}


def instructions(config: Config) -> str:
    scopes = "\n".join(f"- {k}: {v}" for k, v in config.scope_descriptions.items())
    return f"""You index the owner's own mail and chat conversations for later search.
Read the conversation and return:
- question: one line a person would type to find this conversation later (what it is about).
- summary: at most 3 sentences: who, what, key facts and numbers.
- outcome: the decision, answer, agreement or next step; null if there is none.
- entities: up to 15 people, companies, products, amounts, dates or places that matter.
- language: the dominant language of the conversation.
- scope_guess: which part of the owner's life this belongs to, or "unknown":
{scopes}
- scope_confidence: 0..1, how sure you are of scope_guess (below 0.7 means unsure).
Write question, summary and outcome in the conversation's dominant language.
Text marked [REDACTED:...] was removed on purpose; never guess it. Use only what is written."""


# --- provider ------------------------------------------------------------------------------


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


class LlmClient(Protocol):
    def complete(
        self, model: str, system: str, text: str, effort: str
    ) -> tuple[dict[str, Any], Usage]: ...

    def submit_batch(self, model: str, system: str, effort: str, items: dict[str, str]) -> str: ...

    def batch_results(
        self, batch_id: str
    ) -> tuple[str, dict[str, tuple[dict[str, Any] | None, Usage, str | None]]]: ...


def _request_body(model: str, system: str, text: str, effort: str) -> dict[str, Any]:
    return {
        "model": model,
        "instructions": system,
        "input": text,
        "reasoning": {"effort": effort},
        "max_output_tokens": 2000,
        "store": False,
        "text": {
            "format": {"type": "json_schema", "name": "unit", "strict": True, "schema": SCHEMA}
        },
    }


def _body_text(body: dict[str, Any]) -> str:
    for item in body.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    return str(part.get("text") or "")
    return ""


class StructuredLlm(Protocol):
    def structured(
        self, model: str, system: str, text: str, schema: dict[str, Any], name: str, effort: str
    ) -> tuple[dict[str, Any], Usage]: ...


class OpenAIClient:
    def __init__(self) -> None:
        from openai import OpenAI

        self.client = OpenAI()

    def structured(
        self, model: str, system: str, text: str, schema: dict[str, Any], name: str, effort: str
    ) -> tuple[dict[str, Any], Usage]:
        """One structured-output call with any JSON schema (briefs, triage, loops)."""
        body: dict[str, Any] = {
            "model": model,
            "instructions": system,
            "input": text,
            "reasoning": {"effort": effort},
            "max_output_tokens": 4000,
            "store": False,
            "text": {
                "format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}
            },
        }
        r = self.client.responses.create(**body)
        if r.status != "completed":
            raise RuntimeError(f"response status {r.status}: {r.incomplete_details}")
        usage = Usage(r.usage.input_tokens, r.usage.output_tokens) if r.usage else Usage()
        return json.loads(r.output_text), usage

    def complete(
        self, model: str, system: str, text: str, effort: str
    ) -> tuple[dict[str, Any], Usage]:
        r = self.client.responses.create(**_request_body(model, system, text, effort))
        if r.status != "completed":
            raise RuntimeError(f"response status {r.status}: {r.incomplete_details}")
        usage = Usage(r.usage.input_tokens, r.usage.output_tokens) if r.usage else Usage()
        return json.loads(r.output_text), usage

    def submit_batch(self, model: str, system: str, effort: str, items: dict[str, str]) -> str:
        with tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False) as f:
            for custom_id, text in items.items():
                line = {
                    "custom_id": custom_id,
                    "method": "POST",
                    "url": "/v1/responses",
                    "body": _request_body(model, system, text, effort),
                }
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
            path = f.name
        try:
            with open(path, "rb") as fh:
                uploaded = self.client.files.create(file=fh, purpose="batch")
        finally:
            os.unlink(path)
        batch = self.client.batches.create(
            input_file_id=uploaded.id, endpoint="/v1/responses", completion_window="24h"
        )
        return str(batch.id)

    def batch_results(
        self, batch_id: str
    ) -> tuple[str, dict[str, tuple[dict[str, Any] | None, Usage, str | None]]]:
        batch = self.client.batches.retrieve(batch_id)
        out: dict[str, tuple[dict[str, Any] | None, Usage, str | None]] = {}
        if batch.status not in ("completed", "failed", "expired", "cancelled"):
            return str(batch.status), out
        if batch.output_file_id:
            for line in self.client.files.content(batch.output_file_id).text.splitlines():
                row = json.loads(line)
                body = (row.get("response") or {}).get("body") or {}
                u = body.get("usage") or {}
                usage = Usage(int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)))
                try:
                    out[row["custom_id"]] = (json.loads(_body_text(body)), usage, None)
                except (json.JSONDecodeError, TypeError) as exc:
                    out[row["custom_id"]] = (None, usage, f"unparseable output: {exc}")
        if batch.error_file_id:
            for line in self.client.files.content(batch.error_file_id).text.splitlines():
                row = json.loads(line)
                out[row["custom_id"]] = (None, Usage(), json.dumps(row.get("error"))[:300])
        return str(batch.status), out


def default_client(config: Config) -> LlmClient | None:
    if not config.llm.enabled:
        return None
    if config.llm.provider == "openai" and os.environ.get("OPENAI_API_KEY"):
        return OpenAIClient()
    return None


# --- selecting and preparing units -----------------------------------------------------------


def content_hash(title: str | None, raw_text: str) -> str:
    return hashlib.sha256(f"{title or ''}\n{raw_text}".encode()).hexdigest()


def distill_key(content: str, llm: LlmConfig) -> str:
    return f"{content}:{llm.model()}:{PROMPT_VERSION}"


def unit_input(item: dict[str, Any], llm: LlmConfig) -> str:
    kind = {
        "email_thread": "Email thread",
        "tg_conversation": "Telegram conversation",
        "clickup_task": "ClickUp task with its comments",
        "clickup_chat": "ClickUp chat channel, one day",
    }.get(item["kind"], "Conversation")
    text = item["raw_text"]
    if len(text) > llm.max_input_chars:
        text = "[…earlier part omitted…]\n" + text[-llm.max_input_chars :]
    people = ", ".join(item["participants"][:20])
    return f"{kind}: {item['title'] or ''}\nParticipants: {people}\n\n{text}"


def pending(
    conn: Conn, llm: LlmConfig, limit: int, now: datetime | None = None
) -> list[dict[str, Any]]:
    """Settled units whose current content has not been summarized with the current model."""
    now = now or datetime.now(UTC)
    return conn.execute(
        """
        SELECT id, source_id, source_item_key, kind, title, raw_text, participants, scopes,
               content_hash
        FROM items
        WHERE NOT hidden AND kind = ANY(%(kinds)s) AND distill_batch IS NULL
          AND last_activity_at < %(settled)s
          AND distilled_key IS DISTINCT FROM content_hash || ':' || %(model)s || ':' || %(pv)s
        ORDER BY last_activity_at DESC
        LIMIT %(limit)s
        """,
        {
            "kinds": list(UNIT_KINDS),
            "settled": now - timedelta(minutes=llm.settle_minutes),
            "model": llm.model(),
            "pv": PROMPT_VERSION,
            "limit": limit,
        },
    ).fetchall()


# --- applying results -----------------------------------------------------------------------


def cached(conn: Conn, source_id: str, unit_key: str, key: str) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT result FROM distillations "
        "WHERE source_id = %s AND unit_key = %s AND distill_key = %s",
        (source_id, unit_key, key),
    ).fetchone()
    return row["result"] if row else None


def latest_scope_guess(conn: Conn, source_id: str, unit_key: str, min_conf: float) -> str | None:
    row = conn.execute(
        """
        SELECT result FROM distillations WHERE source_id = %s AND unit_key = %s
        ORDER BY created_at DESC LIMIT 1
        """,
        (source_id, unit_key),
    ).fetchone()
    if not row:
        return None
    r = row["result"]
    guess = r.get("scope_guess")
    if guess in SCOPES and float(r.get("scope_confidence") or 0) >= min_conf:
        return str(guess)
    return None


def apply_to_item(
    conn: Conn, source_id: str, unit_key: str, key: str, r: dict[str, Any], llm: LlmConfig
) -> None:
    """Write fields to the unit's item if its content still matches; scope guess only replaces
    'unsorted' (rules always win)."""
    conn.execute(
        """
        UPDATE items SET question = %(q)s, summary = %(s)s, outcome = %(o)s, entities = %(e)s,
            language = %(l)s, distilled_key = %(key)s, distilled_at = now(), distill_batch = NULL,
            scopes = CASE WHEN scopes = '{unsorted}' AND %(guess)s::text IS NOT NULL
                          THEN ARRAY[%(guess)s::text] ELSE scopes END,
            metadata = CASE WHEN scopes = '{unsorted}' AND %(guess)s::text IS NOT NULL
                            THEN metadata || '{"scope_by": "classifier"}'::jsonb ELSE metadata END
        WHERE source_id = %(src)s AND source_item_key = %(unit)s
          AND content_hash || ':' || %(model)s || ':' || %(pv)s = %(key)s
        """,
        {
            "q": r.get("question"),
            "s": r.get("summary"),
            "o": r.get("outcome"),
            "e": json.dumps(r.get("entities") or [], ensure_ascii=False),
            "l": r.get("language"),
            "key": key,
            "guess": (
                r.get("scope_guess")
                if r.get("scope_guess") in SCOPES
                and float(r.get("scope_confidence") or 0) >= llm.scope_min_confidence
                else None
            ),
            "src": source_id,
            "unit": unit_key,
            "model": llm.model(),
            "pv": PROMPT_VERSION,
        },
    )


def store_result(
    conn: Conn,
    source_id: str,
    unit_key: str,
    key: str,
    r: dict[str, Any],
    usage: Usage,
    llm: LlmConfig,
    purpose: str,
) -> None:
    conn.execute(
        """
        INSERT INTO distillations (source_id, unit_key, distill_key, model, result,
                                   input_tokens, output_tokens)
        VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
        """,
        (
            source_id,
            unit_key,
            key,
            llm.model(),
            json.dumps(r, ensure_ascii=False),
            usage.input_tokens,
            usage.output_tokens,
        ),
    )
    record_usage(conn, source_id, llm.model(), purpose, usage)
    apply_to_item(conn, source_id, unit_key, key, r, llm)


def mark_skipped(conn: Conn, item: dict[str, Any], key: str) -> None:
    """Too short to be worth a request: mark as done for this content."""
    conn.execute(
        "UPDATE items SET distilled_key = %s, distilled_at = now() WHERE id = %s", (key, item["id"])
    )


# --- usage and caps -------------------------------------------------------------------------


def record_usage(conn: Conn, source_id: str, model: str, purpose: str, usage: Usage) -> None:
    conn.execute(
        """
        INSERT INTO llm_usage
            (day, source_id, model, purpose, requests, input_tokens, output_tokens)
        VALUES (%s, %s, %s, %s, 1, %s, %s)
        ON CONFLICT (day, source_id, model, purpose) DO UPDATE SET
            requests = llm_usage.requests + 1,
            input_tokens = llm_usage.input_tokens + EXCLUDED.input_tokens,
            output_tokens = llm_usage.output_tokens + EXCLUDED.output_tokens
        """,
        (
            datetime.now(UTC).date(),
            source_id,
            model,
            purpose,
            usage.input_tokens,
            usage.output_tokens,
        ),
    )


def cost_usd(model: str, usage: Usage) -> float:
    price_in, price_out = PRICES.get(model, (0.0, 0.0))
    return (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000


def month_spend_usd(conn: Conn, today: date | None = None) -> float:
    """All server-side AI spend this calendar month (UTC), at list prices: language models plus
    transcription."""
    from kb import transcription

    day = today or datetime.now(UTC).date()
    rows = conn.execute(
        "SELECT model, sum(input_tokens) AS i, sum(output_tokens) AS o FROM llm_usage"
        " WHERE day >= %s AND day <= %s GROUP BY model",
        (day.replace(day=1), day),
    ).fetchall()
    models = sum(cost_usd(r["model"], Usage(int(r["i"]), int(r["o"]))) for r in rows)
    return models + transcription.month_spend_usd(conn, day)


def used_today(conn: Conn, source_id: str, day: date | None = None) -> int:
    row = conn.execute(
        "SELECT coalesce(sum(input_tokens + output_tokens), 0) AS n FROM llm_usage "
        "WHERE day = %s AND source_id = %s",
        (day or datetime.now(UTC).date(), source_id),
    ).fetchone()
    return int(row["n"]) if row else 0


def estimate_tokens(text: str, system_chars: int, cpt: float = CHARS_PER_TOKEN_DEFAULT) -> int:
    return int((len(text) + system_chars) / cpt) + 350  # + expected output


def take_within_cap(
    conn: Conn, items: Iterable[dict[str, Any]], llm: LlmConfig, system_chars: int
) -> list[dict[str, Any]]:
    """Keep items while each source stays under its daily token cap (estimated)."""
    budget: dict[str, int] = {}
    kept = []
    for it in items:
        src = it["source_id"]
        if src not in budget:
            budget[src] = llm.daily_token_cap - used_today(conn, src)
        need = estimate_tokens(unit_input(it, llm), system_chars)
        if budget[src] - need < 0:
            continue
        budget[src] -= need
        kept.append(it)
    return kept


# --- the cycle ------------------------------------------------------------------------------


def poll_batches(conn: Conn, client: LlmClient, config: Config) -> int:
    applied = 0
    for b in conn.execute(
        "SELECT * FROM distill_batches WHERE finished_at IS NULL ORDER BY id"
    ).fetchall():
        status, results = client.batch_results(b["provider_batch_id"])
        if status not in ("completed", "failed", "expired", "cancelled"):
            conn.execute("UPDATE distill_batches SET status = %s WHERE id = %s", (status, b["id"]))
            continue
        for custom_id, ref in b["refs"].items():
            result, usage, error = results.get(custom_id, (None, Usage(), "missing from output"))
            if result is not None:
                store_result(
                    conn,
                    ref["source_id"],
                    ref["unit_key"],
                    ref["key"],
                    result,
                    usage,
                    config.llm,
                    "distill_batch",
                )
                applied += 1
            else:
                log.warning("batch %s item %s failed: %s", b["provider_batch_id"], custom_id, error)
        # Anything not applied becomes pending again.
        conn.execute(
            "UPDATE items SET distill_batch = NULL WHERE distill_batch = %s",
            (b["provider_batch_id"],),
        )
        conn.execute(
            "UPDATE distill_batches SET status = %s, finished_at = now() WHERE id = %s",
            (status, b["id"]),
        )
        log.info("batch %s %s: applied %d", b["provider_batch_id"], status, applied)
    return applied


def run_cycle(
    conn: Conn, config: Config, client: LlmClient, now: datetime | None = None
) -> dict[str, int]:
    """One enrichment step: apply finished batches, then summarize settled units (live for a
    small backlog, Batch API for a big one). Returns counters."""
    llm = config.llm
    stats = {
        "applied_batch": poll_batches(conn, client, config),
        "live": 0,
        "batched": 0,
        "skipped": 0,
    }
    system = instructions(config)
    todo = pending(conn, llm, llm.batch_max, now)
    real = []
    for it in todo:
        key = distill_key(it["content_hash"] or "", llm)
        hit = cached(conn, it["source_id"], it["source_item_key"], key)
        if hit is not None:
            apply_to_item(conn, it["source_id"], it["source_item_key"], key, hit, llm)
        elif len(it["raw_text"]) < llm.min_chars:
            mark_skipped(conn, it, key)
            stats["skipped"] += 1
        else:
            real.append(it)
    real = take_within_cap(conn, real, llm, len(system))
    if len(real) >= llm.batch_threshold:
        refs = {}
        texts = {}
        for i, it in enumerate(real):
            cid = f"u{it['id']}-{i}"
            refs[cid] = {
                "source_id": it["source_id"],
                "unit_key": it["source_item_key"],
                "key": distill_key(it["content_hash"] or "", llm),
            }
            texts[cid] = unit_input(it, llm)
        batch_id = client.submit_batch(llm.model(), system, llm.effort, texts)
        conn.execute(
            "INSERT INTO distill_batches (provider_batch_id, model, status, requests, refs) "
            "VALUES (%s, %s, 'submitted', %s, %s)",
            (batch_id, llm.model(), len(refs), json.dumps(refs)),
        )
        conn.execute(
            "UPDATE items SET distill_batch = %s WHERE id = ANY(%s)",
            (batch_id, [it["id"] for it in real]),
        )
        stats["batched"] = len(real)
        log.info("distill: submitted batch %s with %d units", batch_id, len(real))
        return stats
    for it in real[: llm.live_per_cycle]:
        key = distill_key(it["content_hash"] or "", llm)
        try:
            result, usage = client.complete(llm.model(), system, unit_input(it, llm), llm.effort)
        except Exception:
            log.exception("distill failed for item %s", it["id"])
            continue
        store_result(
            conn, it["source_id"], it["source_item_key"], key, result, usage, llm, "distill"
        )
        stats["live"] += 1
    return stats


# --- cost estimate --------------------------------------------------------------------------


def cost_estimate(conn: Conn, config: Config, now: datetime | None = None) -> dict[str, Any]:
    llm = config.llm
    system_chars = len(instructions(config))
    todo = pending(conn, llm, 1_000_000, now)
    to_send = [it for it in todo if len(it["raw_text"]) >= llm.min_chars]
    in_tokens = sum(estimate_tokens(unit_input(it, llm), system_chars) - 350 for it in to_send)
    out_tokens = 350 * len(to_send)
    price_in, price_out = PRICES.get(llm.model(), (None, None))
    live = (
        None
        if price_in is None
        else round(in_tokens / 1e6 * price_in + out_tokens / 1e6 * (price_out or 0), 2)
    )
    return {
        "model": llm.model(),
        "units_pending": len(todo),
        "units_to_send": len(to_send),
        "units_too_short": len(todo) - len(to_send),
        "est_input_tokens": in_tokens,
        "est_output_tokens": out_tokens,
        "est_cost_usd_live": live,
        "est_cost_usd_batch": None if live is None else round(live / 2, 2),
        "mode": "batch" if len(to_send) >= llm.batch_threshold else "live",
        "daily_token_cap_per_source": llm.daily_token_cap,
    }


def reattach(conn: Conn, source_id: str, unit_key: str, chash: str, scopes: list[str]) -> None:
    """After a unit is rebuilt: copy the newest cached result for this exact content (any model),
    and, if the unit is still unsorted, the newest confident scope guess."""
    hit = conn.execute(
        """
        SELECT distill_key, result FROM distillations
        WHERE source_id = %s AND unit_key = %s AND distill_key LIKE %s
        ORDER BY created_at DESC LIMIT 1
        """,
        (source_id, unit_key, chash + ":%"),
    ).fetchone()
    if hit:
        r = hit["result"]
        conn.execute(
            """
            UPDATE items SET question = %s, summary = %s, outcome = %s, entities = %s,
                language = %s, distilled_key = %s, distilled_at = now()
            WHERE source_id = %s AND source_item_key = %s
            """,
            (
                r.get("question"),
                r.get("summary"),
                r.get("outcome"),
                json.dumps(r.get("entities") or [], ensure_ascii=False),
                r.get("language"),
                hit["distill_key"],
                source_id,
                unit_key,
            ),
        )
    if scopes == ["unsorted"]:
        guess = latest_scope_guess(conn, source_id, unit_key, LlmConfig().scope_min_confidence)
        if guess:
            conn.execute(
                """
                UPDATE items SET scopes = ARRAY[%s::text],
                    metadata = metadata || '{"scope_by": "classifier"}'::jsonb
                WHERE source_id = %s AND source_item_key = %s
                """,
                (guess, source_id, unit_key),
            )
