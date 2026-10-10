# 0007. Scopes per organisation and a people registry
Date: 2026-10-10
Status: accepted

## Context
One person works across Personal, Digisoft (own company), Quokka and RDIM (CMO roles). Mailboxes are
already separate per project; Telegram chats are mixed. Questions are often about a person across
channels. When a CMO contract ends, data is kept.

## Decision
- Scopes: `personal`, `digisoft`, `quokka`, `rdim` (logical, one database). Every row carries scope[].
- Assignment: config rules first (mail account, domain, label, Telegram chat), LLM fallback with
  confidence, low confidence → `unsorted` for review. Default query scope = all.
- Ended contract → scope marked archived: syncing stops, credentials removed, data stays read-only searchable.
- People registry: one person, many identities (email, phone, Telegram id, ClickUp/GitHub user,
  meeting speaker). Auto-match on exact handles, manual merge for the rest.

## Consequences
Scope tagging is mandatory from the first connector. Identity merges must be reversible.
