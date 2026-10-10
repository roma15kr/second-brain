# Roadmap

## Goals this quarter
1. Answer "what did we decide / who said / where is X" across mail and Telegram from Claude in under 10 seconds, for the last 12 months.
2. Replace manual morning catch-up for Quokka and RDIM with an automated CMO standup.

## Now (in progress)
- `v1-mail-telegram-search` — mail + Telegram ingestion, hybrid search, MCP tools (evidence: docs/research/cerebras-knowledge-base.md, design grilling 2026-10-10)

## Next (planned)
- GitHub: code (CocoIndex), issues, PRs, reviews, commits
- ClickUp (Quokka) + Karakeep + Google Calendar
- People registry UI/merge flow; Telegram bot Q&A; daily digest; follow-up tracker
- Metrics warehouse: Meta, Google Ads, GA, TikTok, marketplace, Shopify, Stripe (history) + `query_metrics`
- CMO daily standups (Quokka, RDIM); meeting prep brief; weekly CMO report
- Vaultwarden on Coolify + off-site encrypted export + emergency kit (ADR 0013)
- Ops registry: domains/TLS expiry alerts, subscriptions from receipts, failed-payment alerts, server inventory
- Vault metadata push from Mac, `where_are_credentials`, leaked-secret alerts, weekly vault hygiene report
- macOS meeting assistant (live transcript, live KB assistant, batch re-transcription)

## Later / maybe
- WhatsApp (chat exports or linked-device bridge) — v2 decision
- Public remote-MCP endpoint with OAuth for Claude on mobile
- Per-file code summaries (`subsystem_index`)

## Decided not to do
- Full pseudonymization of data sent to cloud LLMs — query-time answers go through Claude anyway; secrets are redacted instead (2026-10-10, ADR 0005)
- Embedding numeric metrics — warehouse + SQL instead (2026-10-10, ADR 0008)
- Storing meeting video — transcript kept, audio 30 days (2026-10-10, ADR 0010)
