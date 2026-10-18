# External context
Things outside this repository that agents need to know exist. NAMES only, never secret values.

- Environment variables (set in Coolify for the `kb` app):
  - `DATABASE_URL` — Postgres connection string
  - `KB_SECRET_KEY` — encrypts credentials entered in the web OS (IMAP app passwords, ClickUp token, calendar secret addresses); losing it means re-entering them
  - `KB_MCP_TOKEN` — bearer token MCP clients must send
  - `OPENAI_API_KEY` — server-side LLM: distillation, scope classification, digests (set in Coolify, never in chat)
  - `KB_DISTILL_MODEL` — model id for distillation (default `gpt-6-luna`)
  - `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET` — Gmail API OAuth client
  - `IMAP_PASSWORD_<MAILBOX>` — app password per IMAP mailbox (or stored encrypted via `kb auth imap`)
  - `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` — from my.telegram.org; session file on the `telegram` volume
  - `WEB_PUSH_VAPID_PUBLIC_KEY`, `WEB_PUSH_VAPID_PRIVATE_KEY`, `WEB_PUSH_SUBJECT` — Web Push (web-os-v1)
  - `KB_WEB_ORIGIN` — public origin of the web OS (passkey relying party), e.g. https://os.141-94-30-173.sslip.io
- Third-party services and dashboards:
  - Coolify (on the owner's dedicated server) — deployment; dashboard reachable over Tailscale only.
    App `second-brain` (uuid sgu30h2aphvigaaehbsvvjvg), server ns31426159, deploy key `second-brain-deploy`.
    Local tooling reads `COOLIFY_URL`, `COOLIFY_TOKEN` from `.env` (gitignored).
  - MCP test endpoint: https://kb.141-94-30-173.sslip.io/mcp — token in Coolify env `SERVICE_PASSWORD_64_MCPTOKEN`
  - Coolify-generated: `SERVICE_PASSWORD_POSTGRES`; app config in `KB_CONFIG_YAML`; mailbox `IMAP_USER_MAIN`, `IMAP_PASSWORD_MAIN`
  - Tailscale — private network for dashboard, MCP and the Mac app
  - Google Cloud project — Gmail API OAuth client (must be Internal or In production, not Testing)
  - my.telegram.org — Telegram API app credentials
  - OpenAI Platform — API key, usage and monthly spend limit for the server-side LLM
  - ClickUp API v2 — personal API token (Settings → Apps); 100 requests/min per token on Free–Business plans; reads tasks/comments, creates tasks only after approval (web-os-v1)
  - Google Calendar secret iCal address — read-only calendar feed, no OAuth (Settings → Integrate calendar); resetting it in Google breaks sync until replaced
  - Web Push services (Apple, Google, Mozilla push endpoints) — deliver notifications to subscribed devices; no content in payloads
  - Reserve storage (S3-compatible, different provider/region than the server; provider TBD) — Coolify Postgres backups and nightly encrypted Vaultwarden export; its credentials are in the printed emergency kit, not only in the vault
- Test accounts: none yet.
