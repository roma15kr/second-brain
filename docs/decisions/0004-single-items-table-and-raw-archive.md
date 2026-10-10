# 0004. One items table on top of an immutable raw archive
Date: 2026-10-10
Status: accepted

## Context
Data comes from many systems (mail, Telegram, GitHub, ClickUp, Karakeep, meetings, ad platforms).
Cerebras showed that one Postgres table with a fixed row shape, filled by per-source connectors,
keeps retrieval uniform and makes new sources cheap. Unlike Cerebras we cannot always re-fetch
history (Telegram, mail retention, deleted messages), and we expect to change distillation prompts
and embedding models.

## Decision
- Every connector first writes what it fetched, unchanged, to an append-only raw archive (per channel,
  per scope). Day-one backfill indexes the last 12 months; the archive may hold more.
- Everything derived (`items`, embeddings, distillations, people links) is rebuildable from the archive.
- A single `items` table is the retrieval surface for all text sources: raw text + FTS/trigram,
  distilled fields, embedding, scope[], people[], timestamps, JSONB metadata.
- Connectors are plugins that declare: what the data is, how to connect, schedule, scope.

## Consequences
Re-indexing after a prompt/model change is a batch job, not a re-sync. Storage grows (acceptable:
text is small). The raw archive is the most sensitive asset and must be backed up and encrypted.
