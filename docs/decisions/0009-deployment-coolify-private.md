# 0009. Deploy on Coolify, private network by default
Date: 2026-10-10
Status: accepted

## Context
The server will hold a Telegram user session, mail tokens and client ad-account credentials.
Owner deploys with Coolify on a dedicated CPU server.

## Decision
- One Docker Compose application in Coolify: Postgres+pgvector, workers, scheduler, MCP server, bot.
- Tailscale on the host; Coolify dashboard, MCP and the Mac app are reached over the tailnet.
  Internal services get no domain and no published ports.
- No inbound webhooks: Telegram long-polling/MTProto, Gmail Pub/Sub pull or history polling,
  scheduled polling for other APIs.
- Secrets in Coolify env vars; Telegram session on a dedicated volume.
- Backups: Coolify scheduled Postgres backups to S3-compatible storage; restic for the raw archive.
- A public HTTPS remote-MCP endpoint with OAuth is a later, optional addition for Claude on mobile.

## Consequences
Minimal attack surface. Claude.ai web/mobile cannot use the MCP until the public endpoint exists.
Google OAuth apps must not stay in "Testing" mode (refresh tokens expire after 7 days).
