# Proposal: web-os-v1 — the second brain OS on the web, with an assistant routine

Branch: `change/web-os-v1`, created from `kb-design-v1-plan` (depends on `v1-mail-telegram-search`);
PR to `main` after v1 is merged.

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
- v1 data is live: 606 email threads, 2,137 Telegram conversations, AI summaries, people, scopes
  (STATUS.md).

**Success metric:** for 4 consecutive weeks the owner opens or acts on (marks done, snoozes, opens
the source of) items from **≥ 80% of scheduled briefs**, and **≥ 70% of detected open loops** are
resolved (done/dismissed) rather than expiring unseen. Measured from the app's own event log
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
- **Pages:** Today, Inbox (mail revision), Briefs, Week, Loops, Search, Conversation, People and
  Person, Scope, Settings, Status.
- Times, passes and which notifications are pushed are adjustable in Settings.

## Non-goals

- Dictation, call/meeting recording and transcription (native macOS/iOS apps, ADR 0014).
- Chat with the knowledge base inside the web app (later change; Claude via MCP covers it now).
- Sending or drafting replies, changing anything in Gmail or Telegram (read-only stays).
- ClickUp, Calendar, Karakeep and marketing metrics in briefs (sections appear when those sources
  exist; not part of this change).
- Multi-user accounts, sharing, team views.
- Native mobile apps for the dashboard (the PWA is the phone app).

## Announcement

Your second brain now runs your day. Open it on your laptop or add it to your phone's home screen,
sign in with Face ID, and it comes to you: an 08:00 brief with what came in overnight and what
needs you, quick mail check-ins through the day, a 19:00 wrap-up, and every Friday and Monday a look
back at the week and a plan for the next one — across Personal, Digisoft, Quokka and RDIM. Promises
you made and replies you owe are tracked until they are done, and every line links to the original
mail or chat.

## Capabilities

### New Capabilities
- `web-access`: owner sign-in with passkeys and recovery codes, sessions, installable app, push subscriptions.
- `assistant-routines`: scheduled briefs (morning, mail revision, evening, weekly review, weekly plan), their content, delivery and history.
- `open-loops`: detecting, tracking and resolving replies owed, promises and follow-ups across days.
- `web-dashboard`: the OS shell and pages (Today, Inbox, Briefs, Week, Loops, Search, Conversation, People, Scope, Settings, Status).

### Modified Capabilities
- None (no main specs exist yet; v1 capabilities are consumed, not changed).

## Impact

- New web frontend and a JSON API on the existing server; new tables for briefs, loops, push
  subscriptions, passkeys and app events.
- New scheduled jobs in the index service (or a scheduler service).
- OpenAI usage for briefs and loop detection (estimated ≈ $5–10/month, inside the existing cap).
- Docker image gains a frontend build stage; `make check` covers TypeScript too.
- Mockups: `mockups/*.html`, one per screen.
