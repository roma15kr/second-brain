# Architecture

## Overview
second-brain is a single-user, self-hosted knowledge base that ingests the owner's communication
and work systems where they already live (mail, Telegram, GitHub, ClickUp, Karakeep, meetings,
marketing and commerce platforms) and makes them queryable by Claude (via MCP), a Telegram bot and
scheduled automations. The design follows the Cerebras knowledge base
([research note](research/cerebras-knowledge-base.md)): per-source connectors, one shared items
table with full-text + vector indexes, LLM distillation of conversations, hybrid retrieval fused
with RRF and reranked, and thin LLM-free MCP tools. On top of that we keep an immutable raw archive,
a numeric metrics warehouse, a people registry and a macOS meeting assistant.

## Scopes (projects)
`personal`, `digisoft`, `quokka`, `rdim`. Every raw record, item, metric row and credential carries a
scope; a source may belong to several. Default query scope = all; tools accept a scope filter.
Scope assignment: rules (mail account, sender domain, label, Telegram chat → scope) in config,
LLM fallback with confidence, low confidence → `unsorted` for review ([ADR 0007](decisions/0007-scopes-and-people.md)).
Ended contracts: scope switched to archived/read-only — sync stops, data stays searchable.

## Modules
Built in v1 (`v1-mail-telegram-search`), one Python package `kb` (`src/kb/`):

| Module | Responsibility |
|--------|----------------|
| `config.py` | YAML config (`KB_CONFIG_YAML`) + env secrets: sources, scope rules, LLM, embedding, search |
| `db.py`, `migrations/` | Connections, numbered SQL migrations under an advisory lock |
| `archive.py`, `jobs.py` | Lossless append-only raw archive; Postgres job queue (SKIP LOCKED) |
| `connectors/imap.py` | IMAP; Gmail via `\All` + X-GM-THRID/labels; live + backfill cursors; read-only |
| `connectors/telegram.py`, `telegram_auth.py` | Telethon user client, read-only, allowlist; QR/code login |
| `email_parse.py`, `redact.py` | MIME parsing; hard-secret redaction before anything is stored for search |
| `indexer.py`, `units.py` | Raw → messages → conversation units (email threads, Telegram conversations); `INDEX_VERSION` rebuilds |
| `scopes.py` | Scope layers (review rules, config rules, chat, source, classifier), unsorted review, archived scopes |
| `people.py` | Identities (email, Telegram id/username, phone) → people; merge/split/link |
| `distill.py` | OpenAI summaries (live + Batch API), cache, daily caps, cost estimate |
| `embed.py`, `rerank.py` | Local e5-large embeddings + cache; local jina multilingual reranker |
| `idf.py`, `passages.py` | Token rarity; key passages inside long conversations |
| `search.py` | Exact pinning, full-text, rare-term, vector, RRF, rerank, recency tie-break, context, deep links |
| `mcp_server.py` | MCP tools: search, search_mail, search_chats, get_item, recent_activity, person, status; token + lockout |
| `health.py`, `evaluate.py`, `cli.py` | Status (sources, queue, LLM, embeddings, backups), acceptance eval, `kb` CLI |
| `docker/backup.sh` | Daily pg_dump + automatic restore test → `backup_checks` |

Planned (later changes): metrics warehouse, Telegram bot, automations (digest, follow-ups, CMO
standups, meeting prep), ops registry, vault metadata push, macOS meeting assistant.

### Web OS assistant (`assistant-command-v1`)
| Module | Responsibility |
|--------|----------------|
| `assistant/agent.py` | Request loop: OpenAI Responses API with function tools, ≤ 8 calls / 90 s, refs validated, budget fallback, "ready" push |
| `assistant/actions.py` | Action tools: drafts (reply, new email, Telegram, ClickUp task) into the approval queue, reminders/loop changes with undo, activity + reports |
| `api/routes_requests.py` | Requests and threads (background pool in the `web` service), undo, run anyway, report → Library, pin, 90-day cleanup |
| `dictation.py`, `api/routes_dictations.py` | Upload (raw body), background `gpt-transcribe`, audio deleted after transcript, Clean/Structured forms with faithfulness checks |
| `web/src/assistant/` | Ask box (⌘K and Assistant page), thread view, recorder (MediaRecorder + IndexedDB queue), Dictate page |

## Data model (core)
- `raw_records` — source, scope[], external id, fetched_at, payload (JSON/blob ref), content hash.
  Never mutated; new versions appended. All derived tables are rebuildable from here.
- `items` — the single retrieval table (Cerebras pattern): source, source_id, kind
  (thread | segment | burst | email_thread | code_chunk | issue | bookmark | meeting | …), scope[],
  title, raw_text, distilled fields (question, summary, resolution, entities), people[], occurred_at,
  last_activity_at, metadata JSONB, `tsvector` (GIN, `simple` config + unaccent), pg_trgm,
  `embedding vector` (HNSW). Parent/child links for thread → burst and section neighbours.
- `token_df` — document frequency per token for IDF scoring and burst gating.
- `people`, `identities` — one person, many handles (email, phone, Telegram id, ClickUp/GitHub user, voice label).
- `metrics.*` — per-platform fact tables (date, account, campaign, … , spend, clicks, conversions, revenue).
- `sources`, `sync_state` — per-source config (scope, schedule, allow/deny lists) and cursors.

## Data flow
1. **Fetch:** a connector pulls (or receives via outbound long-poll/WebSocket) new data, writes
   `raw_records`. No public inbound webhooks.
2. **Normalize:** build the retrieval unit. Email → whole thread. Telegram → reply chains / forum
   topics; DMs and flat groups → segments split by time gap. Re-built whole whenever a new message joins.
3. **Redact:** strip hard secrets (passwords, card/IBAN, OTP codes, API tokens) before anything leaves the server.
4. **Index lexically** immediately (FTS + trigram) — raw text is searchable within seconds.
5. **Distill** (OpenAI API, batched): question / summary / resolution / entities / scope guess / promises.
6. **Burst** gate (rare token IDF ≥ 4, ≥ 200 chars, reactions) → embed bursts with topic prepended.
7. **Embed** distilled form locally; write `items`.
8. **Query:** MCP tool → parallel retrievers (FTS, vector, IDF-weighted lexical) with scope/time/person
   filters → RRF (k = 60) → dedupe per source, cap per parent → local reranker → top 10 → expand
   neighbours → structured evidence rows with citations (source link, date, people, scope).

## Interfaces
- **MCP (primary):** `search`, `search_mail`, `search_chats`, `search_code`, `recent_activity`,
  `who_knows`, `person`, `get_item`, `query_metrics` (read-only SQL / views), `meetings`,
  `where_are_credentials` (vault pointers only).
  LLM-free; Claude Code / Claude Desktop orchestrate.
- **Telegram bot:** ask questions (planner → executor → synthesis), receive digests and standups,
  forward links/messages for capture.
- **Automations:** daily digest; follow-up tracker (promises by you and others); meeting prep brief
  from Google Calendar; CMO daily standups for Quokka and RDIM (yesterday/today/blockers, metric
  anomalies vs 7-day baseline, decisions from meetings, draft team message); weekly CMO report;
  leaked-secret alerts; weekly vault hygiene report; domain/TLS expiry and subscription renewal /
  failed-payment alerts.
- **Meeting app (macOS):** ScreenCaptureKit system audio + mic as separate tracks (you vs others),
  streaming cloud STT for live transcript, live KB assistant and end-of-call action items; after the
  call batch re-transcription becomes the canonical transcript; audio deleted after 30 days.

## Passwords and secrets
Passwords live in a self-hosted Vaultwarden (Coolify, Tailscale only), never in the KB. The KB only
receives vault metadata pushed from the Mac; see [ADR 0013](decisions/0013-password-vault-and-ops-registry.md).

## Deployment
Coolify on a dedicated CPU server (ns31426159), one Docker Compose app: postgres (pgvector), ingest,
telegram, index, mcp, backup. Only the MCP service has a domain (public HTTPS + bearer token with
lockout, ADR 0009 amendment); all other services have no ports. Secrets as
Coolify env vars; Telegram session on its own volume. Backups: Coolify Postgres backups to S3 +
restic for the raw archive. See [ADR 0009](decisions/0009-deployment-coolify-private.md).

## External dependencies
- Postgres + pgvector, pg_trgm, unaccent; CocoIndex (code); Telethon (Telegram MTProto)
- Gmail API / IMAP; GitHub API; ClickUp API; Karakeep API; Google Calendar API
- Meta (Facebook) Marketing API, Google Analytics Data API, Google Ads API, TikTok Ads API,
  marketplace API(s) (Quokka), Shopify Admin API, Stripe API (historical)
- OpenAI API (distillation, digests; ADR 0005 amendment); Claude via MCP for interactive answers; cloud STT (streaming + batch, uk/ru/en); local embedding
  and reranker models (bge-m3 / bge-reranker-v2-m3 class)
