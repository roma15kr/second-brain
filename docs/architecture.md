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

## Modules (planned; Python core, Swift macOS app)
| Module | Path | Responsibility |
|--------|------|----------------|
| core | `src/kb/core/` | Shared schema, config, scope rules, secret redaction |
| raw archive | `src/kb/archive/` | Append-only store of fetched payloads per source (lossless, re-processable) |
| connectors | `src/kb/connectors/<source>/` | One plugin per source: fetch, cursor/sync state, emit raw records |
| distill | `src/kb/distill/` | Thread/segment building, LLM distillation, burst gating |
| embed | `src/kb/embed/` | Local multilingual embeddings (bge-m3 class) on CPU |
| retrieval | `src/kb/retrieval/` | FTS, vector, IDF, age decay, RRF fusion, rerank, context expansion |
| people | `src/kb/people/` | Person registry: identities per channel, matching, merge |
| metrics | `src/kb/metrics/` | Typed tables for ads/analytics/commerce, read-only SQL views |
| mcp | `src/kb/mcp/` | MCP server exposing retrieval primitives |
| bot | `src/kb/bot/` | Telegram bot: questions, digests, standups, link capture → Karakeep |
| ops registry | `src/kb/ops/` | Servers, domains (RDAP expiry), TLS certs, subscriptions from receipts, vault metadata pointers |
| automations | `src/kb/automations/` | Scheduled jobs: digest, follow-ups, meeting prep, CMO standups, weekly report |
| meeting app | `apps/meeting-mac/` | macOS recorder + live transcript + live KB assistant |
| vault exporter | `apps/vault-push-mac/` | launchd job: `bw` CLI → vault metadata + local hygiene findings pushed to KB (no secrets) |

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
5. **Distill** (cloud LLM, batched): question / summary / resolution / entities / scope guess / promises.
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
Coolify on a dedicated CPU server (8–16 cores, 64 GB RAM, no GPU), one Docker Compose app:
Postgres 16+ with pgvector, worker(s), scheduler, MCP server, Telegram bot. Only the MCP/API service
has a domain; Coolify dashboard, MCP and the Mac app reach the server over Tailscale. Secrets as
Coolify env vars; Telegram session on its own volume. Backups: Coolify Postgres backups to S3 +
restic for the raw archive. See [ADR 0009](decisions/0009-deployment-coolify-private.md).

## External dependencies
- Postgres + pgvector, pg_trgm, unaccent; CocoIndex (code); Telethon (Telegram MTProto)
- Gmail API / IMAP; GitHub API; ClickUp API; Karakeep API; Google Calendar API
- Meta (Facebook) Marketing API, Google Analytics Data API, Google Ads API, TikTok Ads API,
  marketplace API(s) (Quokka), Shopify Admin API, Stripe API (historical)
- Anthropic API (distillation, synthesis); cloud STT (streaming + batch, uk/ru/en); local embedding
  and reranker models (bge-m3 / bge-reranker-v2-m3 class)
