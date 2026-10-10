# Status
_Last updated: 2026-10-10 by Claude_

## Current focus
- Applying `v1-mail-telegram-search`: slice 1 (IMAP → lexical search → MCP) built and deployed to Coolify.
- Test deployment: Coolify app `second-brain` (uuid sgu30h2aphvigaaehbsvvjvg) on ns31426159, branch `kb-design-v1-plan`;
  MCP at https://kb.141-94-30-173.sslip.io/mcp (bearer token = Coolify `SERVICE_PASSWORD_64_MCPTOKEN`);
  registered in Claude Code (user scope) as `second-brain`.
- Active OpenSpec change: `openspec/changes/v1-mail-telegram-search/`

## Done recently
- AI project template installed (`ai-init`).
- Design grilling based on the Cerebras knowledge-base article: `docs/research/cerebras-knowledge-base.md`.
- Architecture in `docs/architecture.md`; decisions in ADRs 0004–0012; roadmap in `docs/product/roadmap.md`.

## Next steps
1. Owner sets `IMAP_USER_MAIN` / `IMAP_PASSWORD_MAIN` (Gmail app password) in Coolify; verify a real email is found via MCP (closes tasks 1.4, 1.5).
2. Owner rotates the Coolify API token (part of it leaked into a session log on 2026-10-10).
3. Start collecting 30 real evaluation questions for `eval/questions.yaml`.
4. Owner adds reserve (off-site) storage: different provider/region; receives nightly encrypted Vaultwarden export and Postgres backups; credentials + export passphrase go in the printed emergency kit; do one test restore (ADR 0013).

## Open questions
- Telegram segmentation by silence gap vs topic shift (design: least confident #1).
- Age decay for personal knowledge (design: least confident #4).
- Is Proton Mail in use (needs Proton Bridge)?
- WhatsApp approach for v2 (Quokka discussions are a known blind spot).

## Known problems / gotchas
- No Docker in the dev workspace: tests use an embedded Postgres (`pgserver`, has pgvector but no pg_trgm/unaccent).
- Public HTTPS MCP endpoint is a test-only deviation from ADR 0009 (Tailscale-only); move before real personal data grows.
- `.env` holds COOLIFY_URL/COOLIFY_TOKEN; the token contains `|` — never `source` the file, read values with grep/cut.
- Google OAuth clients in "Testing" mode expire refresh tokens after 7 days — use Internal / In production.
- Telegram session file = full account access; keep it on its own volume, server reachable via Tailscale only.
