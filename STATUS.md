# Status
_Last updated: 2026-10-19 by Claude_

## Current focus
- **Everything built, waiting for the owner's acceptance test** (one consolidated list below, owner asked to
  test at the end). `web-os-v1`: 36/40 tasks (left: real-device checks 11.3, 12.1, 12.2 and acceptance 14.1).
  `assistant-command-v1`: 10/13 (left: 1.3, 4.3, 5.2 real-device checks). `v1-mail-telegram-search`: 29/30 (10.3).
- Production: Coolify app `second-brain` (uuid sgu30h2aphvigaaehbsvvjvg), branch `main`.
  Web OS https://os.zhukovsky.biz (passkeys) · MCP https://kb.zhukovsky.biz/mcp (token + lockout) · Cloudflare-proxied.

## Owner acceptance checklist (test on phone and laptop, then give feedback)
1. ClickUp: a push arrives when you or DTC are assigned/mentioned (11.3); followed activity is grouped.
2. Inbox → Draft reply → Save to Drafts appears unsent in the Gmail thread (12.1); Send → lands in the thread (12.2).
3. Assistant: one question with sources, an email draft, a task draft, a reminder, a report (assistant 1.3, 5.2).
4. Dictate (🎙): Ukrainian, Russian and mixed; Structured; As a request; the mic in the Ask box (assistant 4.3).
5. Connectors → Calendars: Google secret address and/or iCloud app-specific password; mark calendars; a meeting
   with attendees shows prep 30 min before and a reminder push 10 min before (14.1).
6. Settings → Working hours; morning brief shows focus blocks; evening wrap warns about a heavy tomorrow.
7. Settings → Recorder apps: pairing works once the recorder apps exist (`voice-apps-v1`); until then, attach notes
   or a .vtt/.docx to a meeting → summary, decisions, your loops, team task drafts.
8. Library: upload the constitution and 2026 plans, confirm goals (goal links in priority and the weekly audit
   need confirmed goals).
9. v1 10.3: 30 evaluation questions → `kb eval`.

## Done recently (2026-10-19)
- ClickUp feedback: the owner's inbox is rebuilt (involved tasks from every list, not only synced ones), DMs, group
  DMs and member channels are read (DMs and @mentions push right away), the workspace has its own mark
  (Connectors → ClickUp, "Mark all lists"); data fix: the Adducate workspace and its digisoft lists are quokka.
- web-os-v1 slice 13 (PRs #30–#34): calendars (Google iCal + iCloud CalDAV, read-only, every 10 min), Meetings
  page and Today's meetings, reminders, meeting prep (people, history, loops, tasks, sourced agenda; morning brief
  for meetings before 10:00), recorder-app pairing + upload API, notes import (.txt/.md/.vtt/.srt/.docx), meeting
  processing (summary, decisions, owner loops, team task drafts), meeting audio (resumable upload, playback beside
  the transcript, 12-month expiry, per-project delete, incremental backup, Status), focus blocks, meeting-load
  warnings, decline drafts, weekly attention audit, neglected goals, decision log. Docs: architecture, external.
- Fix: the mailbox config cache could return another config's result when Python reused an object id.
- assistant-command-v1 slice 1 (approved 2026-10-19): Ask box on the Assistant page and "Ask the assistant" in ⌘K;
  requests run in the web service (2 workers, 8 tool calls / 90 s), tools search/get_item/person, answers cite only
  items the tools returned, private documents never read, threads with follow-ups. The web service now gets
  OPENAI_API_KEY.
- assistant-command-v1 slice 2: requests draft email replies, new emails, Telegram replies and ClickUp tasks
  (approval queue, inline in the thread), update their own drafts on follow-ups, add reminders and close/snooze
  loops with Undo; search shows its filters with "Open in Search"; Status shows requests/week and approval rate
  of drafts from requests (targets 15 and 60%).
- assistant-command-v1 slice 3: reports (activity in a period + sections with checked sources, Save to Library as a
  note), over budget = plain search results + "Run anyway" for one request, push "Ready: …" after requests over 30 s
  (device switch "Assistant answers ready"), threads deleted after 90 days unless pinned.
- assistant-command-v1 slice 4: Dictate app (🎙) and a mic in the Ask box: record while the app is open (≤ 15 min,
  stops in background, kept on the device until uploaded), `gpt-transcribe` in the background, audio deleted after the
  transcript; Verbatim / Clean (wording check) / Structured (no invented dates) / As a request; Save to Library.
  Audio volume `kb-dictations` shared by web and routines. Transcription price is a config value
  (`llm.transcribe_usd_per_minute`, 0.006) — check it against OpenAI's price list.
- gmail-digisoft: status shows each folder's cursor vs the server's next UID; no mail since 2026-10-17 is Gmail's own
  state for digisoftou@gmail.com (the owner's new Digisoft mail goes to another, unconnected address).

## Done recently (2026-10-18)
- Nudges and delegation (12.5): overdue promises owed to the owner get a polite follow-up draft (email: Drafts/Send;
  Telegram: copy and open chat); emails resembling a teammate's ClickUp work get a task draft for them; a kind
  discarded 5 times in a row slows to one a day; acceptance per kind on Status. Declines wait for calendars (13.5).
- Priority (12.3): needs-reply/important mail ordered by importance × urgency with a reason (goal link by
  meaning, important/frequent sender, money, deadline words, waiting time) and a quadrant; "Two-minute
  replies" group; morning brief and automatic drafts use the same order. Goal links need confirmed goals.
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
1. Owner: the acceptance checklist above; feedback → fixes.
2. Owner: generate recovery codes (Settings → Security); go through Connectors → Telegram "To mark".
3. Owner: rotate secrets pasted in chat (Coolify API token, Gmail app password, OpenAI key).
4. Owner: add reserve storage → off-site copy of `/backups` (now including `/backups/audio`) + Vaultwarden export.
5. Owner: check `gpt-transcribe` price vs `llm.transcribe_usd_per_minute` (0.006).
6. After acceptance: archive `web-os-v1`, `assistant-command-v1`, `v1-mail-telegram-search` (owner).
7. Next changes: `voice-apps-v1` (macOS/iOS recorder apps against the device API), GitHub/Karakeep, metrics warehouse.

## Open questions
- AI scope classifier (planned in v1 design, never wired): build it, or keep rules + unsorted review?
- Telegram segmentation by silence gap vs topic shift (design: least confident #1).
- Age decay for personal knowledge (design: least confident #4).
- Is Proton Mail in use (needs Proton Bridge)?
- WhatsApp approach for v2 (Quokka discussions are a known blind spot).

## Known problems / gotchas
- The app runs as user `kb`: any new `/data/...` volume must be created and chowned in `docker/Dockerfile`
  (a new named volume takes the image folder's owner; `tests/test_deploy_volumes.py` checks it). Old empty
  root-owned volumes `kb-dictations`/`kb-audio` can be deleted in Coolify.
- Dictation and recorder audio use volumes `kb-dictation-files` and `kb-audio-files` (web + routines; backup
  mounts `kb-audio` read-only); a new service that needs them must mount them too.
- `/api/devices/*` bypasses the session middleware on purpose (device bearer tokens, upload only); never add a
  read endpoint under that prefix.
- Focus blocks appear only when at least one calendar is marked for sync.
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
