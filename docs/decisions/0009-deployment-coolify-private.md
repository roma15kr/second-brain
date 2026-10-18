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

## Amendment 2026-10-12: MCP stays on public HTTPS with a bearer token
Owner decision (option B of three: Tailscale-only, public + token, public + OAuth). The MCP endpoint
`https://kb.141-94-30-173.sslip.io/mcp` remains publicly reachable so it works from any device
without a VPN. Mitigations: a 64-character Coolify-generated token (tokens < 32 chars are refused),
constant-time comparison, lockout of a client IP after 10 wrong tokens in 10 minutes, 120 requests
per minute per client, HTTPS only via Coolify's proxy, no other service published. Risk accepted:
anyone holding the token can read the whole index — rotate it if it may have leaked (Coolify
`SERVICE_PASSWORD_64_MCPTOKEN`, then update MCP clients). Revisit with OAuth if Claude.ai
web/mobile access is wanted. Backups: daily pg_dump + automatic restore test (`backup` service);
off-site copy once the reserve storage exists.
