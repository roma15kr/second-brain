# Status
_Last updated: 2026-10-18 by Claude_

## Current focus
- `v1-mail-telegram-search`: 29/30 tasks done. Remaining: **10.3 acceptance** — owner writes ~30 real
  questions in `eval/questions.yaml` (format: `eval/questions.example.yaml`), then
  `KB_MCP_TOKEN=… kb eval eval/questions.yaml --mcp-url https://kb.141-94-30-173.sslip.io/mcp --min-recall 0.8`.
- Production: Coolify app `second-brain` (uuid sgu30h2aphvigaaehbsvvjvg), ns31426159, branch `main` (switched 2026-10-18 after PR #1).
  MCP `https://kb.141-94-30-173.sslip.io/mcp` (public HTTPS + token + lockout, ADR 0009 amendment).

## Done recently (2026-10-18)
- Baseline OpenSpec specs for the built v1 system in `openspec/specs/` (9 capabilities: source-ingestion,
  secret-redaction, conversation-indexing, scope-assignment, people-directory, knowledge-search,
  mcp-interface, system-health, retrieval-evaluation) — branch `change/v1-baseline-specs`. They differ from
  the v1 deltas where the build differs: public MCP + token + lockout, `status` tool, Gmail via IMAP,
  no AI scope classifier (unmatched → unsorted), enrichment cost controls, backups, eval.
  Archive v1 with `--skip-specs`.
- Proposal `web-os-v1` (routines, open loops, web dashboard, passkeys, push) — branch `change/web-os-v1`, awaiting review.

## Done earlier (2026-10-10 … 10-12)
- Slices 1–9 verified live: Gmail (IMAP extensions) + 12 Telegram chats; redaction; threads/conversations;
  scopes; AI summaries (OpenAI gpt-6-luna, ~$0.33 backfill); local e5 embeddings + pgvector; IDF rare terms;
  exact pinning; jina reranker; passages; people directory; caches make rebuilds free (26 min, no re-embed).
- Ops: `kb status` / MCP `status` (sources, queue, LLM, embeddings, reranker, backups, DB size);
  daily backup with automatic restore test (first: 82 MB dump, counts match); MCP lockout verified live.
- Example eval (5 questions, live): recall@10 1.0, recall@1 0.8, MRR 0.9, p50 1.5 s.

- `web-os-v1` proposal extended (2026-10-18): connectors hub (mail, Telegram dialogs, ClickUp, calendar,
  Library for constitution/plans), meetings (reminders, prep, notes → task drafts), proactive assistant
  with approval queue (priority, reply drafts to Gmail Drafts, nudges, delegation, focus, goals);
  research: `docs/research/react-vs-svelte.md` (React kept), `docs/research/proactive-assistance.md`.
  Owner decisions: React confirmed; dependencies `pypdf`, `python-docx`, `icalendar`,
  `recurring-ical-events` approved; email = Gmail + any IMAP/SMTP with send on tap (10 s undo);
  calendars = Google secret address + Apple iCloud/CalDAV; meeting notes come from our own recorder
  apps (`voice-apps-v1`, next change) via the device API defined here.
  Meeting/call audio stored in the KB for 12 months (ADR 0010 amendment); transcripts forever.
  Branch merged with `change/v1-baseline-specs` (PR #3 now also contains PR #2's commits).

- web-os-v1 slice 1 live (2026-10-18, PR #5): https://os.141-94-30-173.sslip.io — passkey sign-in
  (owner enrolled), Today page with a data-only morning brief (`kb routines run morning`). `make check`
  covers python + ts (~10 min). Coolify `web` service, domain set via API after the first deploy.

## Next steps
1. Owner: 30 evaluation questions → run `kb eval` → tune if recall@10 < 0.8 (task 10.3), then archive the change.
2. Owner: rotate secrets pasted in chat (Coolify API token, Gmail app password, OpenAI key); optionally rotate MCP token.
3. Owner: add reserve storage → off-site copy of `/backups` (backup service) + Vaultwarden export (ADR 0013).
4. Owner: retarget PRs #2 (baseline specs) and #3 (web-os-v1 proposal) to `main` and merge.
5. Next changes (roadmap): ClickUp/Karakeep/Calendar, metrics warehouse, Telegram bot + automations, meeting app.

## Open questions
- AI scope classifier (planned in v1 design, never wired): build it, or keep rules + unsorted review?
- Telegram segmentation by silence gap vs topic shift (design: least confident #1).
- Age decay for personal knowledge (design: least confident #4).
- Is Proton Mail in use (needs Proton Bridge)?
- WhatsApp approach for v2 (Quokka discussions are a known blind spot).

## Known problems / gotchas
- Coolify compose domains for a NEW service can only be set after one deploy has loaded the new compose file.
- First passkey: `kb web setup-code` in the Coolify terminal (web container); codes expire in 1 h.
- Embedding cost scales with input length: ~1 unit/s on the server CPU at 2,000 chars; a full re-embed of ~3k units takes ~50 min.
- Workspace has no `bc`; use `curl -w %{time_total}` for timings.
- After an INDEX_VERSION bump, new mail/messages wait behind the full rebuild in the job queue (minutes); `status` shows the queue.
- Gmail label changes on already-fetched mail are not re-read (no CONDSTORE yet).
- Search items are units (`email_thread`, `tg_conversation`) built from `messages`; a full rebuild (INDEX_VERSION bump) empties search until the replay catches up (minutes).
- MCP tools must raise `ToolError` for expected failures; other exceptions reach clients as a generic error.
- Bumping `INDEX_VERSION` in `src/kb/indexer.py` re-indexes the whole archive on the next `kb index` start.
- Redaction is rule-based (src/kb/redact.py); when a new leak shape is found, add a real-shaped test first.
- Telegram login: codes for a new api_id may not be delivered; use `kb auth telegram --qr` (Coolify terminal, `telegram` container).
- Helper commands (`kb telegram chats`) use a read-only session snapshot; the ingest service keeps the session file locked.
- Telegram session = account access; lives on the `kb-telegram` volume; revoke in Telegram → Settings → Devices.
- No Docker in the dev workspace: tests use an embedded Postgres (`pgserver`, has pgvector but no pg_trgm/unaccent).
- Public HTTPS MCP endpoint is a test-only deviation from ADR 0009 (Tailscale-only); move before real personal data grows.
- `.env` holds COOLIFY_URL/COOLIFY_TOKEN; the token contains `|` — never `source` the file, read values with grep/cut.
- Google OAuth clients in "Testing" mode expire refresh tokens after 7 days — use Internal / In production.
- Telegram session file = full account access; keep it on its own volume, server reachable via Tailscale only.
