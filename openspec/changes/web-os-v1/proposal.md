# Proposal: web-os-v1 — the second brain OS on the web, with an assistant routine

Branch: `change/web-os-v1`, created from `kb-design-v1-plan` (depends on `v1-mail-telegram-search`)
and merged with `change/v1-baseline-specs` (modifies the baseline `source-ingestion` and
`scope-assignment` specs). PR #3 to `main` after PR #2.

## Why

**Problem (in the owner's words):** "My second brain answers questions in Claude, but I still have
to remember to ask. I want one place — on my laptop and phone — that runs my day with me: what came
in overnight, which mails need me, what I promised and to whom, how the week went across Personal,
Digisoft, Quokka and RDIM, and what to focus on next week. It should tell me (push), not wait for me."

**Evidence:**
- Design grilling 2026-10-10: automations requested (daily digest, follow-up tracker, CMO standups,
  weekly report) — `docs/product/roadmap.md`.
- Owner decisions 2026-10-18: web OS as an installable PWA with web push; schedule morning 08:00,
  mail revision several times a day, evening 19:00, weekly review Friday 19:00, weekly plan Monday
  08:00; voice capture moved to native apps (ADR 0014); SPA stack (ADR 0015).
- Owner request 2026-10-18 (revision): connectors in the web OS — personal base (constitution,
  personal and business plans 2026, files marked personal or project), email, ClickUp and Telegram
  marked personal/project; proactive assistance (meeting reminders, mail priority, reply drafts,
  meeting summaries, ClickUp task drafts for the team) based on proven productivity practices
  (`docs/research/proactive-assistance.md`); React vs Svelte benchmark (`docs/research/react-vs-svelte.md`).
- v1 data is live: 606 email threads, 2,137 Telegram conversations, AI summaries, people, scopes
  (STATUS.md).

**Success metric:** for 4 consecutive weeks the owner opens or acts on (marks done, snoozes, opens
the source of) items from **≥ 80% of scheduled briefs**, and **≥ 70% of detected open loops** are
resolved (done/dismissed) rather than expiring unseen; **≥ 60% of assistant suggestions** (reply
drafts, task drafts, nudges) are approved, edited-and-approved, rather than discarded. Measured from the app's own event log
(brief opened, item action), shown on the Status page.

## What Changes

- **Second brain OS on the web:** an installable app (desktop and phone) with an OS-like shell —
  dock of apps, command palette, notification center — over the knowledge base.
- **Owner login with passkeys** (Face ID / Touch ID / security key) and recovery codes.
- **Assistant routine** on a Kyiv-time schedule, each run producing a brief page and a push
  notification:
  - Morning brief 08:00 — overnight activity per scope, what needs a reply, promises due today,
    suggested top 3.
  - Mail revision passes during the day (default 11:00, 14:00, 17:00) — new mail triaged into
    needs-reply / important / FYI / noise; push only when something needs the owner.
  - Evening wrap 19:00 — what was decided today, loops opened and closed, carry-overs to tomorrow.
  - Weekly review Friday 19:00 — the week per scope: decisions, key conversations, people,
    open loops aging, numbers.
  - Weekly plan Monday 08:00 — last week's recap plus a proposed plan for the coming week.
- **Open loops:** replies the owner owes, promises the owner made, promises made to the owner and
  follow-ups — detected from conversations, tracked across days until done, dismissed or snoozed.
- **Connectors in the web OS:** one hub to connect, mark, watch and disconnect sources — email
  (Gmail and any IMAP + SMTP mailbox), Telegram (QR login, choose and mark dialogs), ClickUp
  (choose and mark spaces/lists), calendars (Google secret address; Apple iCloud and other CalDAV
  with an app-specific password; read-only), files and notes, the owner's recorder apps (paired
  devices deliver transcripts directly) and manual notes import. Everything is
  marked **Personal or a project**; new dialogs/lists/calendars wait in "to mark". Planned
  connectors (GitHub, Karakeep, Drive, ads and analytics, marketplaces, Shopify, Stripe, vault/ops)
  and WhatsApp (not possible live) are shown with what they will add. Projects can be added.
- **Personal base (Library):** personal constitution, personal and business plans 2026, notes and
  files, each marked personal or a project, versioned, searchable; core documents give the
  assistant the owner's principles and goals (goals are extracted and confirmed by the owner);
  "AI may read" switch per document.
- **Meetings:** calendar sync, reminders before meetings, prep (people, history, open loops,
  ClickUp tasks, goal, agenda); transcripts arrive straight from the owner's recorder apps (or are
  attached manually) → summary, decisions, the owner's promises as loops, team actions as ClickUp
  task drafts. Meeting and call **audio** is stored too (12 months, then deleted; transcripts kept
  forever), played back in sync with the transcript, backed up (ADR 0010 amendment).
- **Proactive assistant (propose, never act alone):** mail ordered by importance × urgency with the
  reason; reply drafts in the owner's tone with cited context (save to Drafts, or send
  on the owner's tap with 10 s undo — never automatically; Telegram drafts copied by the owner); nudges for overdue promises to the owner; delegation
  and decline suggestions; ClickUp task drafts (created only after approval); focus blocks and
  meeting-load warnings; goal alignment and attention audit in weekly routines; decision log;
  learning from edits and discards.
- **Pages:** Today, Inbox (mail revision), Assistant (approvals), Meetings, Loops, Briefs, Week,
  Search, Conversation, People and Person, Library, Connectors, Scope, Settings, Status.
- Times, passes and which notifications are pushed are adjustable in Settings.

## Non-goals

- Dictation (in-app dictation added by `assistant-command-v1`, ADR 0014 amendment), call/meeting
  recording and transcription themselves (native macOS/iOS apps, ADR 0014,
  next change `voice-apps-v1`); this change only provides device pairing and the upload API they use.
- Chat with the knowledge base inside the web app (later change; Claude via MCP covers it now).
  Lifted by `assistant-command-v1` (approved 2026-10-19): requests by text or voice in the web OS.
- Sending anything automatically. The only writes are approved email drafts, emails sent on the
  owner's tap, and approved ClickUp tasks; Telegram stays read-only; calendars are read-only (no
  automatic time-blocking).
- Building the planned connectors (GitHub, Karakeep, Drive, ads/analytics, marketplaces, Shopify,
  Stripe, vault/ops, WhatsApp export) — only shown on the hub; each is its own later change.
- Multi-user accounts, sharing, team views.
- Native mobile apps for the dashboard (the PWA is the phone app).

## Announcement

Your second brain now runs your day. Open it on your laptop or add it to your phone's home screen,
sign in with Face ID, and it comes to you: an 08:00 brief with what came in overnight and what
needs you, quick mail check-ins through the day, a 19:00 wrap-up, and every Friday and Monday a look
back at the week and a plan for the next one — across Personal, Digisoft, Quokka and RDIM. Promises
you made and replies you owe are tracked until they are done, and every line links to the original
mail or chat. Connect your mail, Telegram, ClickUp and calendars in one place and mark each as
Personal or a project; drop in your constitution and 2026 plans and the assistant plans your weeks
around your goals. Before each meeting you get a reminder and a prep sheet; after it, a summary and
ready-to-approve tasks for the team. Replies to important mail are drafted for you — save it to
Drafts or tap Send. Calls and meetings recorded with your own app land in the knowledge base by
themselves.

## Capabilities

### New Capabilities
- `web-access`: owner sign-in with passkeys and recovery codes, sessions, installable app, push subscriptions.
- `assistant-routines`: scheduled briefs (morning, mail revision, evening, weekly review, weekly plan), their content, delivery and history.
- `open-loops`: detecting, tracking and resolving replies owed, promises and follow-ups across days.
- `web-dashboard`: the OS shell and pages (Today, Inbox, Assistant, Meetings, Loops, Briefs, Week, Search, Conversation, People, Library, Connectors, Scope, Settings, Status).
- `connectors`: connector hub — connect, mark, health, disconnect; catalog of planned connectors.
- `personal-base`: documents and notes marked personal/project, versions, search, core documents and goals.
- `clickup-integration`: ClickUp sync per marked list, tasks created only from approved drafts.
- `calendar-meetings`: read-only calendars, reminders, meeting prep, notes import, summaries and actions.
- `assistant-actions`: proactive suggestions with an approval queue — priority, reply drafts, nudges, delegation, focus, goal alignment, decision log.

### Modified Capabilities
- `source-ingestion`: mailboxes and Telegram dialogs are connected and chosen in the web OS; assistant drafts are never ingested as owner messages.
- `scope-assignment`: scopes are personal or the owner's projects (projects can be added); marks set on the Connectors page act as rules.

## Impact

- New web frontend and a JSON API on the existing server; new tables for briefs, loops, push
  subscriptions, passkeys and app events.
- New scheduled jobs in the index service (or a scheduler service).
- OpenAI usage: briefs and loop detection ≈ $5–10/month; reply drafts (10/day), meeting prep and
  summaries, goals ≈ $8–12/month with `gpt-6.1-sol` — total ≈ $15–20/month, inside the $100 budget.
- Writes outside the server for the first time: email drafts (IMAP APPEND), email sent via SMTP on
  the owner's tap, ClickUp tasks (personal token) — all only after approval.
- Device API for the recorder apps (pairing, per-device tokens, transcript and audio upload).
- Disk: new `kb-audio` volume, ≈ 8–15 GB per year at ~10 meeting hours a week (12-month window), plus
  its backup copy.
- Credentials entered in the web OS are stored encrypted (`KB_SECRET_KEY`).
- Docker image gains a frontend build stage; `make check` covers TypeScript too.
- Mockups: `mockups/*.html`, one per screen.
