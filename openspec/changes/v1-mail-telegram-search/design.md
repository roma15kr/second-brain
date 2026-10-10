# Design: v1 — mail and Telegram knowledge search

## Context

Greenfield: the repository contains only the AI project template (no application code, `STACKS` unset
in the Makefile). Architecture and constraints come from `docs/architecture.md` and ADRs 0004–0012.
Constraints that shape this design:
- One user; dedicated CPU server (8–16 cores, 64 GB RAM, no GPU); deployed via Coolify; private network.
- Mixed uk/ru/en content; Postgres has no Ukrainian stemmer.
- Cloud AI ≤ $100/month total across the whole system (v1 should stay well under $30/month ongoing).
- Query-time path must be LLM-free (spec: mcp-interface) and ≤ 3 s median (spec: knowledge-search).

## Goals / Non-Goals

**Goals:**
- One Python package (`kb`) with three long-running processes (ingest, index, mcp) and a CLI.
- Postgres as the only stateful service: archive, items, job queue, sync state, people.
- Connector plugin interface reusable by later sources (GitHub, ClickUp, Karakeep, metrics, meetings).
- Evaluation harness from day one, so ranking changes are measured, not guessed.

**Non-Goals:**
- Attachment text extraction (attachment file names and types are indexed; content is not) — next change.
- HTML/web UI; people-merge and unsorted review are CLI commands.
- Horizontal scaling, multi-tenant auth, Kubernetes.

## Decisions

### D1. Python 3.12 + uv, psycopg 3, plain SQL migrations
ADR 0011. No ORM: the schema is small and query-heavy (hybrid SQL). Migrations are numbered `.sql`
files applied by a ~50-line runner that records them in `schema_migrations`.
*Alternatives:* SQLAlchemy + Alembic (more ceremony, little benefit for hand-written ranking SQL).

### D2. Postgres is also the queue
Jobs in a `jobs` table claimed with `FOR UPDATE SKIP LOCKED`; `LISTEN/NOTIFY` wakes workers.
*Alternatives:* Redis + RQ/Celery (another service to run and back up). Volume is tiny.

### D3. Raw archive lives in Postgres
`raw_records(payload jsonb)` with a content hash for idempotency; message bodies are small and attachments
aren't stored in v1. One backup mechanism (Coolify's scheduled Postgres backup to S3) covers everything.
This refines ADR 0009: restic is only needed once binary blobs (attachments, audio) arrive.

### D4. Mail connectors
- **Gmail/Workspace:** Gmail API, OAuth installed-app flow run once via `kb auth gmail <mailbox>`;
  refresh token stored in the DB, encrypted with `KB_SECRET_KEY`. Live sync = `history.list` polled every
  60 s from the stored `historyId`; backfill = `messages.list q="after:<date>"` paged. Thread id = Gmail `threadId`.
  The OAuth client must be Internal (Workspace) or In production (personal Gmail) — Testing mode
  expires refresh tokens after 7 days.
- **IMAP (Zoho/own domain/Proton Bridge):** `imapclient`; IDLE on INBOX plus a 5-minute poll of other folders;
  cursor = (UIDVALIDITY, last UID) per folder. Threads assembled from `Message-ID`/`In-Reply-To`/`References`,
  fallback to normalized subject + participants within 30 days.
*Alternative:* IMAP for Gmail too (simpler auth, app passwords) — kept as fallback if OAuth becomes painful.

### D5. Telegram connector
Telethon user client, session stored as a file on its own Docker volume (`/data/telegram`), created
interactively with `kb auth telegram`. Live: event handlers for new/edited/deleted messages, filtered by
the allowlist. Catch-up after downtime: `iter_messages(min_id=last_id)` per allowlisted chat.
Read-only: the client never calls read acknowledgement or send APIs; a test asserts the wrapper exposes
none. Deleted-message events in private chats lack a chat id — resolve by (message id → stored record).

### D6. Conversation units
- Email: one unit per thread; rebuilt when a message joins (the Cerebras "re-fetch whole thread" rule).
- Telegram: reply chain root or forum topic id if present; otherwise sliding segments split at a
  45-minute silence gap (configurable per chat). A reply to an old message joins the old unit.
- A unit is "settled" after 20 minutes without new messages; only settled units are enriched
  (avoids paying for re-distillation on every message of an active chat).

### D7. Redaction in the item text, not the archive
Redaction runs when building item text, so everything downstream (FTS, embeddings, LLM, MCP output)
only sees redacted text; the archive keeps originals. Detectors: Luhn-valid card numbers, IBAN with
checksum, known token formats (`sk-`, `ghp_`, `xox…`, `AKIA…`, JWT, PEM blocks), context patterns for
passwords and one-time codes in en/uk/ru (`password|пароль|код|code|OTP` + adjacent token).
*Alternative:* ML-based PII (Presidio) — rejected for v1 (ADR 0005: only hard secrets).

### D8. Enrichment via Anthropic API
Model configurable (`KB_DISTILL_MODEL`, default the current Haiku-class model). Structured output via a
tool schema: `question, summary, outcome, entities[], scope_guess, scope_confidence, language`. Backfill
uses the Message Batches API (50% cheaper); live uses direct calls. Input truncated to the latest
~8k tokens of a unit. Rough cost: ~25k units × ~2.5k tokens ≈ 60M input tokens one-off — single-digit to
low-double-digit dollars on a Haiku-class batch tier; verify with the `kb cost-estimate` dry run before backfill.

### D9. Local embeddings and reranker
`BAAI/bge-m3` (dense, 1024-d, multilingual, 8k context) via sentence-transformers on CPU; embedded text =
`question + summary + outcome + entities` (Cerebras normalization) for units, `topic + text` for
passages. Before enrichment, a unit gets a provisional embedding of its first ~512 tokens so
semantic search works early. Reranker: `BAAI/bge-reranker-v2-m3` cross-encoder, top 20 → 10, inputs
truncated to 384 tokens. Models downloaded at image build into a cache volume.
*Alternative:* cloud embeddings (higher quality, but ADR 0005 keeps embeddings local).

### D10. Retrieval pipeline (SQL + Python)
Three retrievers run concurrently, each top 50, all honouring filters:
1. **Lexical:** `tsvector('simple', unaccent(text))` + `websearch_to_tsquery`, ranked by `ts_rank_cd`.
2. **Vector:** pgvector HNSW cosine over `embedding`.
3. **Rare-term:** query tokens with IDF ≥ 4.0 (from `token_df`) matched against the FTS index, scored by the sum of matched IDF.
Exact-match boost: if the query is a quoted string, email, number or id-like token, items containing it
verbatim (trigram/ILIKE) are pinned first. Fusion: RRF `Σ 1/(60 + rank)`; collapse passages into their
unit (keep best passage as excerpt); top 20 → rerank → `score × decay(age)` where
`decay = 0.6 + 0.4·exp(-age_days/180)` → top N → expand excerpt with ±2 neighbouring messages.
Burst gate: same author, consecutive, ≥ 200 chars and (rare token IDF ≥ 4 or ≥ 1 reaction).

### D11. MCP server
Official `mcp` Python SDK, streamable HTTP transport on port 8765, bearer token `KB_MCP_TOKEN`.
In Coolify the service publishes the port bound to the Tailscale IP only (`100.x.y.z:8765:8765`), no domain.
Claude Code: `claude mcp add --transport http kb http://<tailnet-host>:8765/mcp --header "Authorization: Bearer …"`.

### D12. Configuration
`config/kb.yaml` (committed, no secrets): scopes, sources (type, mailbox/chat ids, scope rules,
schedule, backfill window, excluded folders), thresholds. Secrets only in env vars (see docs/external).

## Files

| File | Why |
|------|-----|
| `pyproject.toml`, `uv.lock` | Package `kb`, deps, ruff/mypy/pytest config |
| `Makefile` (edit) | `STACKS := python` so `make check` runs ruff, mypy, pytest |
| `docker/Dockerfile` | Python image with model cache |
| `docker-compose.yml` | postgres (pgvector/pgvector:pg16), ingest, index, mcp services; volumes |
| `config/kb.example.yaml` | Documented example config |
| `migrations/0001_core.sql` | raw_records, items, item_messages, jobs, sources, sync_state, schema_migrations |
| `migrations/0002_search.sql` | extensions (vector, pg_trgm, unaccent), FTS/HNSW/trigram indexes, token_df |
| `migrations/0003_people.sql` | people, identities, item_people, merges |
| `src/kb/config.py` | Load + validate YAML and env |
| `src/kb/db.py` | Connection pool, migration runner |
| `src/kb/jobs.py` | Postgres job queue |
| `src/kb/archive.py` | Idempotent raw record writes, rebuild iteration |
| `src/kb/connectors/base.py` | Connector protocol |
| `src/kb/connectors/gmail.py`, `imap.py`, `telegram.py` | Source connectors |
| `src/kb/units/email_threads.py`, `telegram_segments.py` | Build conversation units |
| `src/kb/redact.py` | Secret detectors |
| `src/kb/scopes.py` | Rule engine + LLM fallback handling |
| `src/kb/distill.py` | Anthropic enrichment (live + batch) |
| `src/kb/embed.py` | Embedding + reranker wrappers |
| `src/kb/bursts.py`, `src/kb/idf.py` | Passage gating, document frequencies |
| `src/kb/people.py` | Identity matching, merge/split |
| `src/kb/search.py` | Retrievers, fusion, rerank, decay, expansion |
| `src/kb/mcp_server.py` | Tool definitions |
| `src/kb/cli.py` | `kb migrate|ingest|index|mcp|auth|rebuild|unsorted|people|status|eval|cost-estimate` |
| `eval/questions.example.yaml`, `src/kb/evaluate.py` | Evaluation set format + recall@10/latency report |
| `tests/…` | See test plan |
| `docs/external/README.md` (edit) | Env var names, external services |

## Types and signatures

```python
Scope = Literal["personal", "digisoft", "quokka", "rdim", "unsorted"]

@dataclass(frozen=True)
class RawRecord:
    source_id: str; external_id: str; kind: str; occurred_at: datetime; payload: dict; content_hash: str

class Connector(Protocol):
    source_id: str
    async def backfill(self, since: datetime) -> AsyncIterator[RawRecord]: ...
    async def live(self) -> AsyncIterator[RawRecord]: ...
    async def health(self) -> SourceHealth: ...

@dataclass
class Message:
    id: str; author: Identity; sent_at: datetime; text: str; reply_to: str | None; reactions: int; deleted: bool

@dataclass
class Unit:
    unit_key: str; source_id: str; kind: Literal["email_thread", "tg_conversation"]
    messages: list[Message]; title: str | None

def build_email_units(records: Iterable[RawRecord]) -> list[Unit]: ...
def assign_segment(msg: Message, recent: list[Unit], gap: timedelta) -> str: ...  # returns unit_key
def redact(text: str) -> tuple[str, list[Redaction]]: ...
def match_scope(unit: Unit, source: SourceConfig, rules: list[ScopeRule]) -> list[Scope] | None: ...
async def distill(unit_text: str) -> Distillation: ...
def submit_distill_batch(units: list[Unit]) -> str: ...  # batch id
def embed(texts: list[str]) -> np.ndarray: ...
def rerank(query: str, docs: list[str]) -> list[float]: ...
def qualifying_bursts(unit: Unit, idf: IdfLookup) -> list[Passage]: ...
def link_identities(identity: Identity) -> PersonId: ...
def merge_people(a: PersonId, b: PersonId) -> MergeId: ...
def split_merge(merge_id: MergeId) -> None: ...

@dataclass
class SearchFilters:
    scopes: list[Scope] | None; sources: list[str] | None; chat_or_mailbox: str | None
    person: PersonId | None; date_from: date | None; date_to: date | None

@dataclass
class Evidence:
    item_id: str; source: str; scopes: list[Scope]; title: str; participants: list[str]
    matched_at: datetime; last_activity_at: datetime; summary: str | None
    excerpt: list[Message]; link: str | None; score: float

def search(query: str, filters: SearchFilters, limit: int = 10) -> list[Evidence]: ...
```

## Call stacks

**Live Telegram message**
`kb ingest` → `TelegramConnector.live()` (event, allowlist check) → `archive.put(RawRecord)` (hash dedupe)
→ `jobs.enqueue("unit.update", key)` → `kb index` worker → `assign_segment` → `redact` → upsert `items`
(raw text + tsvector, provisional embedding) → `idf.update` → if unit settled: `jobs.enqueue("unit.enrich")`
→ `distill` → `match_scope`/LLM scope → `qualifying_bursts` → `embed` → update `items` + passages.

**Gmail backfill**
`kb ingest` startup → `GmailConnector.backfill(now-12mo)` pages → `archive.put` → `jobs.enqueue("unit.update")`
(units rebuilt per thread) → index worker as above, but enrichment collected → `submit_distill_batch`
→ poll batch → write distillations → `embed`.

**MCP search**
Client → `mcp_server.search(query, filters)` → token check → `search()` → `embed(query)` + parallel
SQL retrievers (lexical, vector, rare-term, exact pin) → RRF → collapse → `rerank` → decay → expand
→ `list[Evidence]` → JSON.

**Rebuild**
`kb rebuild --source tg-main` → iterate `archive` → same index path, no connector calls.

## Test plan

Unit (no network, no models — models stubbed with deterministic fakes):
- `test_redact_card_luhn_valid_redacted_invalid_kept` — only Luhn-valid numbers redacted.
- `test_redact_password_context_en_uk_ru` — `password:`, `пароль:` values redacted.
- `test_redact_keeps_phone_price_order_date`.
- `test_redact_known_token_formats` — sk-, ghp_, AKIA, JWT, PEM.
- `test_email_threads_from_references_and_fallback_subject`.
- `test_tg_segment_split_on_gap` / `test_tg_late_reply_joins_old_unit` / `test_tg_forum_topic_is_unit`.
- `test_scope_rule_beats_llm` / `test_low_confidence_is_unsorted` / `test_resolve_as_chat_rule_applies_to_existing`.
- `test_burst_gate_filler_rejected_rare_token_accepted_reaction_accepted`.
- `test_rrf_consensus_beats_single_top` / `test_collapse_passage_into_unit` / `test_decay_prefers_recent_on_tie`.
- `test_link_identities_exact_email_phone_not_name` / `test_merge_then_split_restores`.
- `test_telegram_wrapper_has_no_write_methods` — read-only guarantee.
- `test_mcp_unknown_scope_error_lists_valid` / `test_mcp_requires_token`.

Integration (Postgres in Docker via `make test-integration`, fake connectors feeding recorded fixtures):
- `test_ingest_idempotent_twice_same_rows`.
- `test_restart_resumes_backfill_cursor`.
- `test_tg_edit_updates_search_delete_hides`.
- `test_exact_string_ranks_first` / `test_cross_language_fixture_top10` (with real bge-m3, marked `slow`).
- `test_search_filters_scope_person_dates`.
- `test_rebuild_from_archive_makes_no_connector_calls`.
- `test_search_latency_p50_under_3s_on_seeded_50k_items` (marked `slow`).

Acceptance: `kb eval eval/questions.yaml` → recall@10 ≥ 0.8, p50 ≤ 3 s (proposal success metric).

## Migration Plan

New system, no data migration. Deploy order: Postgres → `kb migrate` → `kb auth` for each source →
`kb ingest` + `kb index` → `kb cost-estimate` → backfill → `kb mcp`. Rollback = stop services; data
stays in Postgres; `kb rebuild` regenerates derived data.

## Risks / Trade-offs

- [Telegram account restriction for automated user clients] → read-only, allowlist, Telethon flood-wait
  handling, conservative backfill rate (≤ 1 request/s).
- [Telegram session theft = account takeover] → session on a dedicated volume, server reachable only via
  Tailscale, owner can revoke via Telegram "Active sessions".
- [CPU reranker breaks 3 s budget] → 384-token truncation, top 20 only; fallback to skip reranking above a time budget (results still fused).
- [bge-m3 quality on short uk/ru chat] → measured by the eval set; swap model via config + `kb rebuild`.
- [Redaction misses a secret format] → detectors are additive and unit-tested; archive keeps originals so re-redaction is a rebuild.
- [Gmail OAuth in Testing mode] → documented in D4 and the auth command prints a warning.
- [LLM cost overrun on chatty groups] → enrich only settled units, per-source daily token cap, batch API for backfill.

## Open Questions

- Exact silence gap and settle time per chat type (tuned with the eval set; defaults set above).
- Whether Proton is actually used (Bridge container only if yes).

## Least confident decisions

1. **Time-gap segmentation for Telegram DMs (45 min).** Real conversations interleave topics; topic-shift detection may be needed. Challenge with real chats before building enrichment.
2. **Raw archive inside Postgres instead of files/object storage.** Simple now; may bloat backups once attachments arrive.
3. **CPU cross-encoder reranker within 3 s.** If too slow, the alternative is a cloud reranker (contradicts query-time LLM-free/local intent) or dropping rerank.
4. **Age decay formula and 180-day half-life.** Personal knowledge (contracts, agreements) doesn't expire like infra answers in Slack; decay may hurt.
5. **Provisional embedding before enrichment.** Doubles embedding work; may be unnecessary if enrichment latency is low.
6. **Own Postgres job queue instead of a library (e.g. Procrastinate).** Less dependency, more code to get right.
7. **Gmail API vs IMAP for Gmail.** API gives thread ids and labels; IMAP avoids the OAuth publishing hassle.
