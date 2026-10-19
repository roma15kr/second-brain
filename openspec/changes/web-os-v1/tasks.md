# Tasks

Each slice ends runnable with its tests passing (`make check`) and is committed separately on
branch `change/web-os-v1`.

## 1. Tracer bullet: signed-in Today page showing one data-only morning brief

- [x] 1.1 Add root `package.json` (npm workspaces → `web/`) and scaffold `web/` (Vite + React + TS, ESLint, Prettier, Vitest); set `STACKS := python ts`; verify `make check` runs both stacks and passes with one trivial test per stack
- [x] 1.2 Add FastAPI app `kb.api` serving `/api/health` and the built SPA with history fallback, `kb web` command and `web` compose service; multi-stage Dockerfile builds `web/dist`; verify `test_spa_fallback_serves_index` and `docker compose up web` shows the SPA
- [x] 1.3 Migration 0011 (auth, settings, routine_runs, briefs tables only); passkey registration with setup code and sign-in, session cookie, CSRF header; verify `test_all_routes_require_session`, `test_setup_code_required_for_first_passkey`, `test_csrf_header_required_on_post`
- [x] 1.4 `kb routines run morning` builds a fact pack and stores a data-only brief; `GET /api/today` and the Today page render it with source links to Gmail/Telegram; verify `test_factpack_morning_window_and_scopes`, `today.test.tsx`, and a manual sign-in on the deployed `web` service

## 2. Scheduler and push

- [x] 2.1 `kb routines` loop with `due_slots` (Europe/Kyiv), `claim` and catch-up once, `routines` compose service; verify `test_due_slots_kyiv_dst`, `test_claim_is_idempotent`, `test_catch_up_once_after_downtime`
- [x] 2.2 Service worker (vite-plugin-pwa injectManifest), manifest and install; push subscriptions per device and routine, VAPID sending, quiet hours, gone-subscription cleanup; verify `sw.test.ts`, `test_push_payload_has_no_content`, `test_gone_subscription_deleted`, `test_quiet_hours_no_push_but_brief_stored`, and a real push on the owner's phone (manual)

## 3. AI briefs

- [x] 3.1 AI sections for morning brief and evening wrap (`gpt-6.1-sol`, structured output), ref validation, data-only fallback on budget cap, cost recorded per run; verify `test_brief_refs_validated_unknown_ids_dropped`, `test_data_only_brief_when_budget_reached`
- [x] 3.2 Briefs list and brief page with rating, `app_events` brief_opened/rating; verify `briefs.test.tsx` and that opening a brief from a push records `brief_opened`

## 4. Mail revision (Inbox)

- [x] 4.1 Triage passes (sender prefs → `gpt-6-luna`), revision brief, push only on needs_reply/important; verify `test_revision_quiet_pass_no_push`, `test_revision_needs_reply_pushes`, `test_sender_noise_pref`
- [x] 4.2 Inbox page with groups and actions (open in Gmail, done, snooze, change scope, sender noise/important); verify `inbox.test.tsx`

## 5. Open loops

- [x] 5.1 Owner identities in settings; deterministic needs-reply loops for email with auto-close on owner reply; `loop_events`; verify `test_needs_reply_closes_when_owner_replies`
- [x] 5.2 `loops.detect` job after summaries (promises by/to owner, due phrase resolution), dismissed sources never recreated; verify `test_loop_detect_promise_by_owner_with_due`, `test_promise_to_owner`, `test_chitchat_no_loop`, `test_resolve_due_phrases_uk_ru_en`, `test_dismissed_source_not_recreated`
- [x] 5.3 Manual actions (done, dismiss, snooze, due date, add), overdue/aging, Loops page with filters; loops in morning brief and evening wrap fact packs; verify `test_snooze_returns_on_date`, `test_overdue_marked`, `loops.test.tsx`

## 6. Weekly routines

- [x] 6.1 Friday weekly review and Monday weekly plan (previous week recap + up to 5 priorities), accept/edit plan, accepted priorities in morning briefs, Week page; verify `test_weekly_plan_accept_feeds_morning_brief` and `week.test.tsx`

## 7. Knowledge pages and OS shell

- [x] 7.1 OS shell: dock / bottom bar, ⌘K command palette (people, briefs, pages, search), notification center; verify `shell.test.tsx`
- [x] 7.2 Search and Conversation pages over existing `kb.search` and items (matched message highlighted, scope edit, related loops); briefs searchable; verify `search.test.tsx` and `test_brief_found_by_search`
- [x] 7.3 People, Person (link/merge/undo merge) and Scope (activity, loops, archive) pages; verify `people.test.tsx` and API tests for merge/undo

## 8. Settings, recovery and Status

- [x] 8.1 Settings page and `/api/settings` (schedule, passes, quiet hours, push toggles, identities, budget cap, scope rules, unsorted review); verify `test_settings_validation` and that a changed morning time moves the next slot
- [x] 8.2 Recovery codes, devices list, sign out one/everywhere, lockout after 10 failures; verify `test_recovery_code_single_use`, `test_sign_out_everywhere`, `test_login_lockout_after_10_failures`
- [x] 8.3 Status page (sync health, routine runs, queue, backups, AI spend, 28-day usefulness metric) and offline read-only mode; verify `test_usefulness_metric_28_days`, `offline.test.tsx`

## 9. Connectors hub and marks

- [x] 9.1 `scopes` table (add/rename/archive projects), `secrets.py` (AES-GCM, `KB_SECRET_KEY`), `connector_accounts`; connect a mailbox from the web — Gmail preset or any IMAP + SMTP server (both connections tested, default mark, picked up without restart); verify `test_add_project_scope`, `test_secret_roundtrip_and_never_returned_by_api`, `test_wrong_imap_password_not_saved`, `test_new_account_ingested_without_restart`
- [x] 9.2 Telegram dialogs in `tg_dialogs` (read-only listing), include/ignore and mark from the web with backfill, "to mark" list, QR login from the web; config allowlist imported once; verify `test_new_dialog_not_ingested_until_included`, `test_mark_change_rescopes_items`, `test_telegram_wrapper_has_no_write_methods`
- [x] 9.3 Connectors hub page (states, counts, catalog with planned and WhatsApp "not possible"), mail rules and "senders to mark", disconnect keep/remove; verify `test_disconnect_keep_vs_remove`, `connectors.test.tsx`

## 10. Personal base (Library)

- [x] 10.1 Add `pypdf` and `python-docx` (approved by the owner 2026-10-18); documents and notes with required mark, versions, text extraction, indexed for web search and MCP; verify `test_extract_md_pdf_docx`, `test_document_requires_mark`, `test_versions_latest_indexed`, `library.test.tsx`
- [x] 10.2 "AI may read" switch enforced in every prompt builder; goals proposed from core documents and confirmed by the owner; Library page per mockup; verify `test_ai_disallowed_document_never_in_prompt`, `test_goals_proposed_need_confirmation`

## 11. ClickUp

- [x] 11.1 Connect with a personal token, choose and mark spaces/lists, sync tasks and comments with cursors and 429 back-off, link members to people; verify `test_sync_list_incremental_cursor`, `test_429_backoff_resumes` (recorded fixtures) and Quokka tasks searchable on production
- [x] 11.2 Task suggestions executor (created only after approval, idempotent, linked to source); closed tasks close linked loops; due tasks in the morning brief; verify `test_task_created_only_from_approved`, `test_create_task_idempotent_retry`, `test_closed_task_closes_loop`
- [ ] 11.3 Push the owner right away for ClickUp tasks/comments assigned to or @mentioning the owner or the DTC group (once each, quiet hours respected, listed in the next brief); verify `test_mention_of_owner_notifies_once`, `test_group_assignment_notifies`, `test_own_comments_and_old_items_do_not_notify`, `test_pending_notifications_pushed_by_routines`, and a real push on the owner's phone

## 12. Proactive assistant

- [ ] 12.1 Tracer: `suggestions` queue, Assistant page (approve / edit / discard), Gmail draft executor (IMAP APPEND, threaded) and draft skipping in ingest; verify `test_draft_saved_to_drafts_not_sent`, `test_draft_not_ingested_and_loop_stays_open`, `assistant.test.tsx`, and one approved draft appears in the real Gmail thread unsent
- [ ] 12.2 Send on tap: `outbox` with 10-second undo, SMTP send from the receiving mailbox, threaded, Sent copy for non-Gmail; verify `test_send_only_after_tap_single_message`, `test_undo_within_10s_nothing_sent`, `test_sent_threaded_and_copied_to_sent_non_gmail`, `test_no_bulk_send_endpoint`, and one real reply sent from Gmail lands in its thread
- [x] 12.3 Eisenhower priority with reasons (goal link, person, money, deadline, waiting) in Inbox and morning brief; two-minute "do now" group; verify `test_priority_goal_linked_first_with_reason`
- [ ] 12.4 Reply drafts with tone examples and cited context (email → Drafts or Send on tap; Telegram → copy and open chat), daily cap; verify draft refs validated and the cap respected (stubbed LLM)
- [x] 12.5 Nudges for overdue promises to the owner, delegation suggestions by teammate area (decline suggestions moved to 13.5: they need meeting load); learning from discards; acceptance rates on Status; verify `test_nudge_for_overdue_owed_to_me`, `test_delegate_matches_teammate_area`, `test_discard_rate_lowers_frequency`

## 13. Calendar and meetings

- [x] 13.1 Add `icalendar` + `recurring-ical-events` (approved 2026-10-18); connect Google calendars by secret address and Apple iCloud / CalDAV with an app-specific password, mark calendars, sync events, Meetings page, reminders before meetings; verify `test_ics_recurring_expanded_kyiv`, `test_caldav_discovery_icloud_fixture`, `test_caldav_report_time_range`, `test_calendar_client_has_no_write_methods`, `test_declined_and_all_day_not_reminded`, `meeting.test.tsx`, and the owner's iCloud calendar on Today
- [x] 13.2 Meeting prep at T-30 (or in the morning brief before 10:00) with people, history, loops, ClickUp tasks, goals and agenda; verify `test_prep_and_reminder_times` and a real prep on the owner's phone
- [x] 13.3 Device pairing (Settings → Devices, one-time code/QR, revoke) and recording upload API for the recorder apps, matched to calendar events or saved as unscheduled calls; manual notes import (paste, .txt/.md/.vtt/.srt/.docx); processing → summary, decisions, owner's loops, team task drafts; verify `test_pairing_code_single_use_and_expires`, `test_device_token_cannot_read_kb`, `test_recording_matched_to_overlapping_event`, `test_unscheduled_call_created`, `test_revoked_device_refused`, `test_upload_idempotent`, `test_notes_to_loops_and_task_drafts`
- [ ] 13.4 Meeting audio: `kb-audio` volume, resumable chunked upload per track with checksum, playback with transcript sync (tap a line → seek), download, 12-month retention and delete per recording/scope, incremental audio backup and storage on Status; ADR 0010 amendment; verify `test_resumable_upload_continues_from_received_length`, `test_checksum_mismatch_rejected`, `test_range_playback_requires_session`, `test_retention_deletes_audio_keeps_transcript`, `test_delete_scope_audio`, `test_audio_backup_copies_new_files_and_verifies`, `meeting.test.tsx`
- [ ] 13.5 Focus blocks and meeting-load warning in briefs; decline/defer suggestions with a polite draft when the week is overloaded and the commitment serves no confirmed goal; attention audit, neglected goals and decision log in weekly routines; verify `test_focus_blocks_and_meeting_load_warning`, `test_neglected_goal_in_weekly_review`

## 14. Deploy and acceptance

- [ ] 14.1 Deploy `web` and `routines` on Coolify with VAPID env vars, `KB_SECRET_KEY` and the `os.` domain; register passkeys on phone and laptop, install the app, enable push; connect ClickUp and calendars, upload the constitution and 2026 plans, confirm goals; verify one full day of routines, a meeting reminder with prep, and an approved reply draft in Gmail
- [ ] 14.2 Update `docs/architecture.md`, `docs/external/README.md` and `STATUS.md` (done, next steps, open questions, gotchas)

## Workflow follow-up

- Open a PR from `change/web-os-v1` to `main` after `kb-design-v1-plan` is merged; the owner merges and archives.
