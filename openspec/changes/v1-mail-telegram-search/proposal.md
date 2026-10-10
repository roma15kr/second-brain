# Proposal: v1 — mail and Telegram knowledge search

## Why

**Problem (in the owner's words):** "My knowledge is scattered across personal and work mailboxes,
Telegram, and the tools of two companies where I'm CMO plus my own company. I can't quickly find
what was agreed, who said what, or where a file or decision is — and my AI assistant can't see any of it."

**Evidence:**
- Design grilling session, 2026-10-10 (decisions recorded in `docs/decisions/0004`–`0012`).
- Research: `docs/research/cerebras-knowledge-base.md` — the same problem at company scale, solved by
  per-source ingestion into one hybrid-searchable store exposed to agents through MCP.
- Mail and Telegram were chosen as the first slice: they're where most daily communication for all
  four scopes happens, and they exercise the hardest retrieval problems (short messages, threads,
  mixed uk/ru/en).

**Success metric:** On a fixed evaluation set of 30 real questions written by the owner (e.g. "what
did we agree with X about Y", "where did someone send the contract"), the expected message or thread
is among the top 10 results returned by `search` for **≥ 80%** of questions, with median response
time **≤ 3 s**. Measured by an eval script run against production data after the 12-month backfill.

**Why now:** every later feature (CMO standups, follow-up tracker, meeting prep, the live meeting
assistant) queries this store; it has to exist first.

## What Changes

- Continuous ingestion of all configured mailboxes (Gmail/Workspace and generic IMAP) and of
  allowlisted Telegram chats from the owner's own account, with a 12-month backfill.
- A lossless archive of everything fetched, so indexes can be rebuilt without re-fetching.
- Every ingested item is assigned to one or more scopes (personal, digisoft, quokka, rdim), by rules
  first and by AI classification as a fallback; uncertain items are marked unsorted.
- Hard secrets (passwords, card/bank numbers, one-time codes, API keys) are redacted before any
  content is sent to an external AI service.
- Conversations become searchable units (whole email threads; Telegram reply chains, topics or
  time-separated segments), each enriched with an AI summary, the question it answers and its outcome.
- Hybrid search that combines exact-word, meaning-based and rarity-based matching with a preference
  for recent material, returning cited evidence.
- A basic people directory linking a person's email addresses and Telegram identity.
- MCP tools for Claude Code / Claude Desktop: `search`, `search_mail`, `search_chats`, `get_item`,
  `recent_activity`, `person`.
- Deployable on the owner's server through Coolify, reachable only over the private network.

## Non-goals

- WhatsApp, GitHub, ClickUp, Karakeep, Google Calendar, meeting transcripts, marketing/commerce metrics.
- Telegram bot, digests, follow-up tracker, standups and other automations.
- A web UI or answer synthesis on the server — Claude composes answers from the MCP tool results.
- Public internet access to the MCP server; multi-user access control.
- Manual people-merge UI (merges are done via config in v1).
- Purging scopes; archived scopes stay read-only searchable.

## Announcement

Your second brain can now answer from your mail and Telegram. Ask Claude "what did Oleh and I agree
about the RDIM budget?" or "find the Quokka marketplace contract someone sent last spring", and it
searches a year of email from every mailbox plus the Telegram chats you've chosen, then shows the exact
messages with links and dates. Each result is labelled Personal, Digisoft, Quokka or RDIM, so you can
narrow a search to one project. Everything runs on your own server; passwords and card numbers are
removed before any text reaches an AI service.

## Capabilities

### New Capabilities
- `source-ingestion`: fetching mail and Telegram (live and 12-month backfill), allowlists, the lossless archive, sync health.
- `scope-assignment`: assigning items to personal/digisoft/quokka/rdim, unsorted review, archived scopes.
- `secret-redaction`: removing hard secrets before content leaves the server.
- `conversation-indexing`: turning messages into searchable conversation units with AI enrichment and highlighted passages.
- `knowledge-search`: hybrid ranked retrieval with filters and cited evidence.
- `people-directory`: one person across email and Telegram identities.
- `mcp-interface`: the MCP tools exposed to Claude clients and their contracts.

### Modified Capabilities
- None (no existing specs).

## Impact

- Greenfield: first application code in the repository, a database and a deployable service.
- New external dependencies: Gmail API / IMAP servers, Telegram (MTProto user session), Anthropic API,
  local embedding and reranking models.
- New sensitive assets on the server: Telegram session, mail credentials, archive of private messages.
- Cloud AI spend (backfill + ongoing), within the ≤ $100/month budget.
