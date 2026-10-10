# External context
Things outside this repository that agents need to know exist. NAMES only, never secret values.

- Environment variables (set in Coolify for the `kb` app):
  - `DATABASE_URL` — Postgres connection string
  - `KB_SECRET_KEY` — encrypts stored OAuth refresh tokens and IMAP passwords
  - `KB_MCP_TOKEN` — bearer token MCP clients must send
  - `ANTHROPIC_API_KEY` — distillation / scope classification
  - `KB_DISTILL_MODEL` — model id for distillation (default Haiku-class)
  - `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` — Gmail API OAuth client
  - `IMAP_PASSWORD_<MAILBOX>` — app password per IMAP mailbox (or stored encrypted via `kb auth imap`)
  - `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — from my.telegram.org; session file on the `telegram` volume
- Third-party services and dashboards:
  - Coolify (on the owner's dedicated server) — deployment; dashboard reachable over Tailscale only.
    App `second-brain` (uuid sgu30h2aphvigaaehbsvvjvg), server ns31426159, deploy key `second-brain-deploy`.
    Local tooling reads `COOLIFY_URL`, `COOLIFY_TOKEN` from `.env` (gitignored).
  - MCP test endpoint: https://kb.141-94-30-173.sslip.io/mcp — token in Coolify env `SERVICE_PASSWORD_64_MCPTOKEN`
  - Coolify-generated: `SERVICE_PASSWORD_POSTGRES`; app config in `KB_CONFIG_YAML`; mailbox `IMAP_USER_MAIN`, `IMAP_PASSWORD_MAIN`
  - Tailscale — private network for dashboard, MCP and the Mac app
  - Google Cloud project — Gmail API OAuth client (must be Internal or In production, not Testing)
  - my.telegram.org — Telegram API app credentials
  - Anthropic Console — API key, usage and spend limits
  - Reserve storage (S3-compatible, different provider/region than the server; provider TBD) — Coolify Postgres backups and nightly encrypted Vaultwarden export; its credentials are in the printed emergency kit, not only in the vault
- Test accounts: none yet.
