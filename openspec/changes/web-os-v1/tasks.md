# Tasks

Each slice ends runnable with its tests passing (`make check`) and is committed separately on
branch `change/web-os-v1`.

## 1. Tracer bullet: signed-in Today page showing one data-only morning brief

- [ ] 1.1 Add root `package.json` (npm workspaces → `web/`) and scaffold `web/` (Vite + React + TS, ESLint, Prettier, Vitest); set `STACKS := python ts`; verify `make check` runs both stacks and passes with one trivial test per stack
- [ ] 1.2 Add FastAPI app `kb.api` serving `/api/health` and the built SPA with history fallback, `kb web` command and `web` compose service; multi-stage Dockerfile builds `web/dist`; verify `test_spa_fallback_serves_index` and `docker compose up web` shows the SPA
- [ ] 1.3 Migration 0011 (auth, settings, routine_runs, briefs tables only); passkey registration with setup code and sign-in, session cookie, CSRF header; verify `test_all_routes_require_session`, `test_setup_code_required_for_first_passkey`, `test_csrf_header_required_on_post`
- [ ] 1.4 `kb routines run morning` builds a fact pack and stores a data-only brief; `GET /api/today` and the Today page render it with source links to Gmail/Telegram; verify `test_factpack_morning_window_and_scopes`, `today.test.tsx`, and a manual sign-in on the deployed `web` service

## 2. Scheduler and push

- [ ] 2.1 `kb routines` loop with `due_slots` (Europe/Kyiv), `claim` and catch-up once, `routines` compose service; verify `test_due_slots_kyiv_dst`, `test_claim_is_idempotent`, `test_catch_up_once_after_downtime`
- [ ] 2.2 Service worker (vite-plugin-pwa injectManifest), manifest and install; push subscriptions per device and routine, VAPID sending, quiet hours, gone-subscription cleanup; verify `sw.test.ts`, `test_push_payload_has_no_content`, `test_gone_subscription_deleted`, `test_quiet_hours_no_push_but_brief_stored`, and a real push on the owner's phone (manual)

## 3. AI briefs

- [ ] 3.1 AI sections for morning brief and evening wrap (`gpt-6.1-sol`, structured output), ref validation, data-only fallback on budget cap, cost recorded per run; verify `test_brief_refs_validated_unknown_ids_dropped`, `test_data_only_brief_when_budget_reached`
- [ ] 3.2 Briefs list and brief page with rating, `app_events` brief_opened/rating; verify `briefs.test.tsx` and that opening a brief from a push records `brief_opened`

## 4. Mail revision (Inbox)

- [ ] 4.1 Triage passes (sender prefs → `gpt-6-luna`), revision brief, push only on needs_reply/important; verify `test_revision_quiet_pass_no_push`, `test_revision_needs_reply_pushes`, `test_sender_noise_pref`
- [ ] 4.2 Inbox page with groups and actions (open in Gmail, done, snooze, change scope, sender noise/important); verify `inbox.test.tsx`

## 5. Open loops

- [ ] 5.1 Owner identities in settings; deterministic needs-reply loops for email with auto-close on owner reply; `loop_events`; verify `test_needs_reply_closes_when_owner_replies`
- [ ] 5.2 `loops.detect` job after summaries (promises by/to owner, due phrase resolution), dismissed sources never recreated; verify `test_loop_detect_promise_by_owner_with_due`, `test_promise_to_owner`, `test_chitchat_no_loop`, `test_resolve_due_phrases_uk_ru_en`, `test_dismissed_source_not_recreated`
- [ ] 5.3 Manual actions (done, dismiss, snooze, due date, add), overdue/aging, Loops page with filters; loops in morning brief and evening wrap fact packs; verify `test_snooze_returns_on_date`, `test_overdue_marked`, `loops.test.tsx`

## 6. Weekly routines

- [ ] 6.1 Friday weekly review and Monday weekly plan (previous week recap + up to 5 priorities), accept/edit plan, accepted priorities in morning briefs, Week page; verify `test_weekly_plan_accept_feeds_morning_brief` and `week.test.tsx`

## 7. Knowledge pages and OS shell

- [ ] 7.1 OS shell: dock / bottom bar, ⌘K command palette (people, briefs, pages, search), notification center; verify `shell.test.tsx`
- [ ] 7.2 Search and Conversation pages over existing `kb.search` and items (matched message highlighted, scope edit, related loops); briefs searchable; verify `search.test.tsx` and `test_brief_found_by_search`
- [ ] 7.3 People, Person (link/merge/undo merge) and Scope (activity, loops, archive) pages; verify `people.test.tsx` and API tests for merge/undo

## 8. Settings, recovery and Status

- [ ] 8.1 Settings page and `/api/settings` (schedule, passes, quiet hours, push toggles, identities, budget cap, scope rules, unsorted review); verify `test_settings_validation` and that a changed morning time moves the next slot
- [ ] 8.2 Recovery codes, devices list, sign out one/everywhere, lockout after 10 failures; verify `test_recovery_code_single_use`, `test_sign_out_everywhere`, `test_login_lockout_after_10_failures`
- [ ] 8.3 Status page (sync health, routine runs, queue, backups, AI spend, 28-day usefulness metric) and offline read-only mode; verify `test_usefulness_metric_28_days`, `offline.test.tsx`

## 9. Deploy and acceptance

- [ ] 9.1 Deploy `web` and `routines` on Coolify with VAPID env vars and the `os.` domain; register passkeys on phone and laptop, install the app, enable push; verify one full day of routines arrives on the phone at the scheduled times
- [ ] 9.2 Update `docs/architecture.md`, `docs/external/README.md` and `STATUS.md` (done, next steps, open questions, gotchas)

## Workflow follow-up

- Open a PR from `change/web-os-v1` to `main` after `kb-design-v1-plan` is merged; the owner merges and archives.
