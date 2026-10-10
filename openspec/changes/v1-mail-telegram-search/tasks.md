# Tasks

Each slice ends runnable with its tests passing (`make check`) and is committed separately.

## 1. Tracer bullet: one IMAP mailbox → exact search over MCP

- [x] 1.1 Scaffold `pyproject.toml` (uv, ruff, mypy, pytest), set `STACKS := python` in the Makefile, add `docker-compose.yml` with pgvector Postgres; verify `make check` passes on an empty test suite and `docker compose up -d postgres` is healthy
- [x] 1.2 Add `kb.config`, `kb.db` migration runner and `migrations/0001_core.sql` (raw_records, items, sources, sync_state, schema_migrations); verify `kb migrate` is idempotent (test: running twice applies nothing new)
- [x] 1.3 Implement `archive.put` with content-hash dedupe and an IMAP connector for one folder (INBOX, UID cursor); verify `test_ingest_idempotent_twice_same_rows` against recorded IMAP fixtures
- [x] 1.4 Build one item per email (no threading yet) with `tsvector('simple', unaccent)`; add `search()` lexical-only and MCP `search` tool with bearer token; verify `test_mcp_requires_token` and a manual `claude mcp add` query returns a seeded email
- [x] 1.5 Add `docker/Dockerfile`, `ingest`/`index`/`mcp` services and `config/kb.example.yaml`; verify `docker compose up` ingests a real test mailbox and Claude Code finds a message by an exact word

## 2. Telegram live ingestion (lexical)

- [x] 2.1 `kb auth telegram` creates the session on the `telegram` volume; read-only Telethon wrapper with allowlist; verify `test_telegram_wrapper_has_no_write_methods` and a non-allowlisted chat stores nothing
- [x] 2.2 Live handlers for new/edited/deleted messages + catch-up from last id; verify `test_tg_edit_updates_search_delete_hides` and that messages stay unread in the Telegram app (manual check)
- [x] 2.3 Add `search_chats` and `search_mail` MCP tools (source filter); verify an allowlisted message is found within 2 minutes end to end

## 3. Secret redaction

- [x] 3.1 Implement `kb.redact` (cards with Luhn, IBAN, token formats, password/OTP context en/uk/ru) and apply it when building item text; verify the redaction unit tests in the design test plan pass
- [x] 3.2 Verify archive keeps originals and MCP output shows `[REDACTED:…]` (integration test on a fixture message containing an OTP and a password)

## 4. Conversation units

- [ ] 4.1 Email threading (Gmail-style thread id hook, References/In-Reply-To, subject fallback) with whole-thread rebuild on new message; verify `test_email_threads_from_references_and_fallback_subject` and that a reply yields one updated result
- [ ] 4.2 Telegram segmentation (reply chains, forum topics, 45-min gap, late replies) with configurable gap; verify `test_tg_segment_split_on_gap`, `test_tg_late_reply_joins_old_unit`, `test_tg_forum_topic_is_unit`
- [ ] 4.3 `get_item` and `recent_activity` MCP tools with pagination and clear errors; verify `test_mcp_unknown_scope_error_lists_valid` and paging over a 300-message fixture

## 5. Scopes

- [ ] 5.1 Scope rule engine (mailbox, domain/address, label, chat) from `kb.yaml`; every item gets scopes or `unsorted`; scope filter in all search tools; verify `test_scope_rule_beats_llm` (with LLM stubbed) and scope-filter integration test
- [ ] 5.2 `kb unsorted list|assign [--apply-to-chat|--apply-to-sender]` and archived-scope handling (sync stops, search still returns); verify `test_resolve_as_chat_rule_applies_to_existing` and an archived-scope integration test

## 6. Gmail connector and backfill

- [ ] 6.1 `kb auth gmail` OAuth flow (encrypted refresh token, warns about Testing mode); live sync via `history.list`; verify against recorded API fixtures and a real mailbox (new mail searchable < 5 min)
- [ ] 6.2 Backfill for Gmail, IMAP (all non-excluded folders) and Telegram (allowlisted chats) with resumable cursors and rate limiting, running alongside live sync; verify `test_restart_resumes_backfill_cursor`
- [ ] 6.3 `kb rebuild --source` from archive; verify `test_rebuild_from_archive_makes_no_connector_calls`

## 7. Enrichment

- [ ] 7.1 Settled-unit detection and `distill` via Anthropic tool schema (question, summary, outcome, entities, scope guess, language), redacted input only; LLM scope fallback with confidence threshold → `unsorted`; verify with a stubbed client (`test_low_confidence_is_unsorted`) and one live call on a fixture
- [ ] 7.2 Batch distillation for backfill + `kb cost-estimate` dry run + per-source daily token cap; verify cost estimate output on fixture data and that the cap stops enqueueing

## 8. Semantic and hybrid search

- [ ] 8.1 `migrations/0002_search.sql` (vector, pg_trgm, HNSW, token_df); bge-m3 embedding of provisional and distilled text; vector retriever; verify `test_cross_language_fixture_top10` (slow)
- [ ] 8.2 IDF maintenance, rare-term retriever, exact-match pin, RRF fusion and unit collapse; verify `test_rrf_consensus_beats_single_top`, `test_collapse_passage_into_unit`, `test_exact_string_ranks_first`
- [ ] 8.3 Cross-encoder rerank with time budget, age decay, neighbour expansion, `Evidence` with deep links; verify `test_decay_prefers_recent_on_tie` and `test_search_latency_p50_under_3s_on_seeded_50k_items` (slow)
- [ ] 8.4 Burst passages (gate: ≥ 200 chars and rare token or reaction; topic prepended); verify `test_burst_gate_filler_rejected_rare_token_accepted_reaction_accepted` and the "detail buried in a long thread" scenario on a fixture

## 9. People directory

- [ ] 9.1 `migrations/0003_people.sql`; create people from correspondents, auto-link on exact email/phone only; person filter in search; verify `test_link_identities_exact_email_phone_not_name`
- [ ] 9.2 `kb people merge|split|show` and the `person` MCP tool; verify `test_merge_then_split_restores` and a merged person filter returning both channels

## 10. Operations and acceptance

- [ ] 10.1 Sync health (`kb status` + health in logs; unhealthy after 3× interval or auth failure); verify the expired-credentials scenario with a revoked fixture token
- [ ] 10.2 Deploy on Coolify: Compose app, MCP port bound to the Tailscale IP only, no domain, env vars per docs/external, scheduled Postgres backup to S3; verify the MCP is unreachable from the public IP and reachable from Claude Code over Tailscale, and a backup restores into a scratch database
- [ ] 10.3 Owner writes `eval/questions.yaml` (30 real questions + expected items); `kb eval` reports recall@10 and latency; verify recall@10 ≥ 0.8 and p50 ≤ 3 s on production data after backfill (tune gap/decay/thresholds if not)
- [ ] 10.4 Update `docs/architecture.md` (actual modules), `AGENTS.md` (run/test commands, testing traps) and `STATUS.md` (done, next steps, gotchas); verify `openspec validate --all` passes

## Workflow follow-up

- Owner reviews and merges; archive the change with `/opsx:archive` once 10.3 passes.
