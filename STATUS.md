# Status
_Last updated: 2026-10-18 by Claude_

## Current focus
- `web-os-v1` (branch `change/web-os-v1`, merged slice by slice into `main` and deployed): 25/39 tasks.
  Next: slice 11 ClickUp, 12 proactive assistant (drafts, send on tap), 13 calendars/meetings/audio, 14 acceptance.
- `v1-mail-telegram-search`: 29/30 tasks. Remaining: **10.3 acceptance** — owner writes ~30 real questions in
  `eval/questions.yaml` (format: `eval/questions.example.yaml`), then
  `KB_MCP_TOKEN=… kb eval eval/questions.yaml --mcp-url https://kb.zhukovsky.biz/mcp --min-recall 0.8`.
- Production: Coolify app `second-brain` (uuid sgu30h2aphvigaaehbsvvjvg), branch `main`.
  Web OS https://os.zhukovsky.biz (passkeys) · MCP https://kb.zhukovsky.biz/mcp (token + lockout) · Cloudflare-proxied.

## Done recently (2026-10-18)
- Assistant (12.1, 12.2, 12.4 email): Assistant page = approval queue; "Draft reply" in Inbox; up to 5 AI
  reply drafts a day (Settings) in the thread's language and the owner's tone, KB context with checked refs;
  Save to Drafts (IMAP, threaded) or Send on tap with 10 s undo (SMTP from the receiving mailbox). Fixed: Gmail
  drafts were stored with label `Draft` (no backslash) and could close needs-reply loops.
- ClickUp notifications (11.3): pushes for tasks/comments assigned to or mentioning the owner or the DTC
  group (immediately, quiet hours respected), followed tasks/comments/chat channels (≤1 push per 15 min);
  "ClickUp for you" page `/clickup`; group name on the ClickUp connector page. Re-marking a list re-labels its
  tasks and comment chunks; the ClickUp login email counts as the owner's (People no longer lists it).
- web-os-v1 live, PRs #5–#15:
  - slice 1–2: React PWA, passkeys, Today brief, Kyiv scheduler, Web Push (verified on iPhone), domains;
  - slice 3–4: AI morning/evening briefs (gpt-6.1-sol, refs validated, budget → data-only), Briefs pages,
    mail revision 11/14/17 (gpt-6-luna triage, sender prefs) + Inbox;
  - slice 5–6: open loops (needs-reply from triage, promises with due dates uk/ru/en, auto-close), Loops page,
    weekly review (Fri) and plan (Mon, accept/edit, priorities in morning briefs);
  - slice 7: OS shell (dock, ⌘K palette, bell), Search via MCP internal route, Conversation, People/Person/Scope;
  - slice 8: Settings, Security (recovery codes, devices, lockout), Status (28-day usefulness), offline mode;
  - slice 9: Connectors hub — projects, encrypted mailboxes (IMAP+SMTP), Telegram dialogs + QR login on the page;
  - slice 10: Library (PDF/Word/Markdown/notes, versions, search), "AI may read" enforced for MCP, goals.
- Proposal research: `docs/research/react-vs-svelte.md` (React kept), `docs/research/proactive-assistance.md`;
  owner decisions: Gmail + IMAP/SMTP with send on tap, Apple iCloud CalDAV, own recorder apps (`voice-apps-v1`),
  meeting audio 12 months (ADR 0010 amendment).
- Baseline OpenSpec specs for v1 in `openspec/specs/` (PR #4); archive v1 with `--skip-specs`.
- Test suite 17 → 4 min (schema built once, tables emptied with DELETE).

## Done earlier (2026-10-10 … 10-12)
- v1 slices 1–9 live: Gmail (IMAP extensions) + Telegram; redaction; threads/conversations; scopes; AI summaries;
  local e5 embeddings + pgvector; IDF; exact pinning; reranker; passages; people; caches make rebuilds free.
- Ops: `kb status` / MCP `status`; daily backup with automatic restore test; MCP lockout verified live.
- Example eval (5 questions): recall@10 1.0, recall@1 0.8, MRR 0.9, p50 1.5 s.

## Next steps
1. Owner: generate recovery codes (Settings → Security) — the first passkey predates them.
2. Owner: go through Connectors → Telegram "To mark"; upload constitution and 2026 plans to the Library, confirm goals.
3. Owner: 30 evaluation questions → `kb eval` (v1 task 10.3), then archive v1 with `--skip-specs`.
4. Owner: rotate secrets pasted in chat (Coolify API token, Gmail app password, OpenAI key).
5. Owner: add reserve storage → off-site copy of `/backups` + Vaultwarden export (ADR 0013).
6. Next changes: `voice-apps-v1` (macOS/iOS recorder + dictation), GitHub/Karakeep, metrics warehouse.

## Open questions
- AI scope classifier (planned in v1 design, never wired): build it, or keep rules + unsorted review?
- Telegram segmentation by silence gap vs topic shift (design: least confident #1).
- Age decay for personal knowledge (design: least confident #4).
- Is Proton Mail in use (needs Proton Bridge)?
- WhatsApp approach for v2 (Quokka discussions are a known blind spot).

## Known problems / gotchas
- Mail executors (Save to Drafts, Send) run in the `routines` service: it needs IMAP_USER_MAIN/IMAP_PASSWORD_MAIN; a send leaves 10–40 s after the tap (30 s cycle).
- Test DB: schema is built once per session; each test empties tables with DELETE (TRUNCATE costs ~3 s per test). `make check` ≈ 4 min.
- Gmail All Mail includes drafts (label `\Draft`): never treat them as the owner's reply.
- Domains moved to os./kb.zhukovsky.biz (Cloudflare-proxied) on 2026-10-18: passkeys and Home Screen apps are per domain, so re-enrol (`kb web setup-code`) and reinstall after any domain change.
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
