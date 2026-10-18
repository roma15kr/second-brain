# 0012. Connector choices and v1 order
Date: 2026-10-10
Status: accepted

## Decision
- v1: Gmail/Workspace (Gmail API) and other IMAP mailboxes (Zoho/own domain; Proton via Bridge if used),
  Telegram userbot on the owner's account (MTProto, read-only, chat allowlist), MCP search.
- Next: GitHub (code via CocoIndex + issues/PRs/reviews/commits), ClickUp, Karakeep (web capture inbox,
  synced via API; links forwarded to the bot land in Karakeep), Google Calendar, metrics sources, meetings.
- WhatsApp is skipped in v1 (no official API for personal accounts; bridges violate ToS). Known gap:
  Quokka discussions on WhatsApp are invisible to standups until v2 revisits (export or bridge).

## Consequences
The Telegram session file is equivalent to account access and must be protected like a password.
