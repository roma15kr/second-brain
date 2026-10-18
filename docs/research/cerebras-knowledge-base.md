# Research: How Cerebras built its knowledge base

Source: https://www.cerebras.ai/blog/how-we-built-our-knowledge-base (read 2026-10-10)
Scale there: >15,000 questions/day, used by humans, automations and agents, ~3 months after launch.

## Core ideas we reuse
1. **Meet data where it lives.** No "single source of truth" migration; one connector per platform.
   Each data source declares what the data is, how to connect, and how often to fetch.
2. **One Postgres table** holding embeddings, raw summaries and metadata from every source
   (`source`, `source_id`, `embedding` (3072-d there), metadata such as channel/authors/time).
   Anything written into it is immediately queryable through the same interface.
3. **Distill before embedding (Slack threads).** Raw transcript is not embedded. An LLM extracts:
   a one-line question someone would search for, a short summary, the resolution, systems and
   code references. Normalizing threads into a consistent format raised accuracy significantly.
   Raw text is keyword-searchable immediately via a Postgres full-text (GIN) index.
4. **Thread = one row, re-fetched whole.** On any new reply the ingester re-pulls parent + all replies
   and rewrites the row, so participants and last-activity are always complete.
   Real-time via Slack Socket Mode (WebSocket push), dedup on stable event ID. One data source per
   channel so freshness can be tuned per channel.
5. **Bursting.** A burst = consecutive messages by one author. Embedded separately with the thread
   topic prepended (contextual retrieval) so a tangent answer is findable. Gate before embedding:
   contains a rare token (IDF >= 4.0), combined length >= 200 chars, social boost if reactions.
6. **Hybrid retrieval, no single scorer trusted:** full-text (exact error strings, flags, hosts),
   embeddings (paraphrase), IDF (rare tokens beat "sounds good, thanks"), age decay (answers expire).
7. **Fusion and reranking.** Reciprocal rank fusion: score += weight / (60 + rank) per list (weight 1.0,
   k = 60) — consensus beats a single strong vote. Merge duplicate chunks to one source, cap results
   per file, keep a diverse top 20 → small reranker model scores 0–10 → keep top 10 → expand winners
   with neighbouring sections (heading, preconditions, caveats).
8. **Code** via CocoIndex: language-aware split coarse→fine (class → method → block), file-level and
   function-level records, incremental re-embedding of changed chunks per commit; sync state lives
   in the same Postgres. Repos onboarded via config with path allow/deny lists.
9. **Custom sources as plugins:** a small Python module that reads a system and emits rows in the
   shared schema. Nothing else in the stack changes.
10. **Tools:** `subsystem_index` (per-file LLM summaries), `search` (unified, fused, reranked),
    `search_slack`, `search_code` (ripgrep), `recent_prs`, `who_knows` (expertise).
11. **MCP exposes primitives, LLM-free where possible;** the agent (Claude Code) orchestrates.
    The web UI runs planner → parallel executor (normalized evidence schema with scores, recency,
    source hints) → synthesis with citations.
12. **Projects** = named bundles of data sources; a source can be in several projects; a default
    project on the user profile scopes queries automatically.

## Where our system differs (see docs/decisions/0004+)
- Single user, multiple organisations → scopes for relevance and offboarding, not for ACLs.
- Raw archive kept as-is per channel; all derived data is rebuildable from it.
- Personal data → local embeddings, cloud LLM only under API terms, secrets redacted.
- Telegram/email have no Slack-style threads → conversation segmentation by reply chain / time gap.
- Marketing/commerce data is numeric → metrics warehouse + SQL tool, not embeddings.
- uk/ru/en content → multilingual embeddings, `simple` FTS config + trigram.

## References cited by the article
HNSW (Malkov & Yashunin 2018); Anthropic "Contextual Retrieval" (2024); RRF (Cormack et al., SIGIR 2009);
Search-o1 (2025); Anthropic "Code execution with MCP" (2025); "Lost in the Middle" (Liu et al. 2023);
Anthropic "Use XML tags"; Slack Engineering "How Slack AI processes billions of messages";
Cursor "Improving agent with semantic search" (2025).
