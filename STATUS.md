# Status
_Last updated: 2026-10-10 by Claude_

## Current focus
- Planning done for v1 (mail + Telegram + MCP search); awaiting owner review of the proposal.
- Active OpenSpec change: `openspec/changes/v1-mail-telegram-search/`

## Done recently
- AI project template installed (`ai-init`).
- Design grilling based on the Cerebras knowledge-base article: `docs/research/cerebras-knowledge-base.md`.
- Architecture in `docs/architecture.md`; decisions in ADRs 0004–0012; roadmap in `docs/product/roadmap.md`.

## Next steps
1. Owner reviews proposal/specs/design/tasks of `v1-mail-telegram-search`, then `/opsx:apply`.
2. Confirm ADR 0011 (Python core) before slice 1.
3. Start collecting 30 real evaluation questions for `eval/questions.yaml`.
4. Owner adds reserve (off-site) storage: different provider/region; receives nightly encrypted Vaultwarden export and Postgres backups; credentials + export passphrase go in the printed emergency kit; do one test restore (ADR 0013).

## Open questions
- Telegram segmentation by silence gap vs topic shift (design: least confident #1).
- Age decay for personal knowledge (design: least confident #4).
- Is Proton Mail in use (needs Proton Bridge)?
- WhatsApp approach for v2 (Quokka discussions are a known blind spot).

## Known problems / gotchas
- Google OAuth clients in "Testing" mode expire refresh tokens after 7 days — use Internal / In production.
- Telegram session file = full account access; keep it on its own volume, server reachable via Tailscale only.
