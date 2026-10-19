# Tasks

Each slice ends runnable with its tests passing (`make check`), is committed separately on branch
`change/assistant-command-v1`, merged to `main` and deployed.

## 1. Tracer bullet: ask a question in text, get a cited answer

- [x] 1.1 Migration: `assistant_threads`, `assistant_requests`; `kb.assistant.agent` tool loop (cap 8 calls / 90 s) with `search`, `get_item`, `person` tools, ref validation and redacted storage; verify `test_agent_answer_cites_only_tool_results`, `test_agent_stops_at_tool_cap`, `test_private_document_never_read` (with a scripted fake LLM)
- [x] 1.2 `POST /api/assistant/requests` + `GET .../{id}` with steps, thread pool, interrupted requests marked failed on startup; verify `test_request_runs_in_background_and_reports_steps`, `test_running_requests_failed_after_restart`, `test_assistant_routes_require_session`
- [ ] 1.3 Assistant page (threads, thread view, answer with ref chips) and palette "Ask the assistant" mode; verify `Assistant.test.tsx` (palette request opens thread, polling shows steps then answer) and a real question answered on production

## 2. Actions from requests

- [x] 2.1 Migration: `suggestions.origin`, `suggestions.thread_id`, kind `email`; tools `draft_reply`, `draft_email`, `draft_task`, `draft_tg_reply`, `update_suggestion` (own thread, proposed only); verify `test_request_creates_reply_draft_not_sent`, `test_new_email_mailbox_choice`, `test_task_draft_list_assignee_due`, `test_follow_up_updates_pending_draft`, `test_update_suggestion_refuses_other_threads`
- [x] 2.2 Loop tools `add_loop`, `loop_action` with undo; `search` results with understood filters; verify `test_remind_me_creates_loop_with_due`, `test_loop_change_undo`, `test_search_request_returns_filters`
- [x] 2.3 Inline suggestion cards (approve/edit/discard), loop undo and search results in the thread view; `app_events` for the metric (requests per week, approval rate by origin) on the Status page; verify `Assistant.test.tsx` cases and `test_status_assistant_metric`

## 3. Reports, budget and push

- [x] 3.1 `report` tool using fact-pack helpers, report view, "Save to Library" as a note with a project mark (indexed); verify `test_report_sections_cite_sources`, `test_saved_report_is_searchable_note`
- [x] 3.2 Budget gate (monthly spend + estimate, "Run anyway" per request), cost per request, push `assistant` routine for requests > 30 s, 90-day thread cleanup (pinned kept); verify `test_over_budget_request_runs_search_only`, `test_run_anyway_one_request`, `test_long_request_pushes`, `test_old_threads_deleted_pinned_kept`

## 4. Dictation

- [x] 4.1 Migration `dictations`; `POST /api/dictations` upload (≤ 25 MB), transcription with `gpt-transcribe`, audio deleted on success and kept 7 days on failure with retry; verify `test_audio_deleted_after_transcript`, `test_failed_transcription_retried_then_deleted`, `test_transcript_redacted`
- [x] 4.2 Forms: Clean (`gpt-6-luna` + content-word check), Structured (`gpt-6.1-sol` schema + no-invented-dates check), As a request; Save to Library; history 90 days; verify `test_clean_keeps_wording_or_falls_back`, `test_structured_drops_invented_due_dates`, `test_mixed_language_kept`, `test_dictation_saved_as_note`
- [ ] 4.3 `Recorder` (MediaRecorder mime detection, 10 s slices in IndexedDB, stop on background, 15-min limit, upload retry) and Dictation sheet with the four forms; mic button in the request field (transcript shown before sending); verify `Recorder.test.tsx` (mocked MediaRecorder: limit, background stop, offline retry), `Dictation.test.tsx`, and a real dictation on the owner's iPhone and Mac

## 5. Docs and acceptance

- [ ] 5.1 ADR 0014 amendment (in-app dictation in the web OS), web-os-v1 proposal non-goal pointer, `docs/architecture.md`, `STATUS.md`; verify `openspec validate --all` passes
- [ ] 5.2 Owner acceptance on production: 5 requests (question, email draft, task draft, reminder, report) and 3 dictations (uk, ru, mixed) behave as the spec scenarios say; record results in STATUS.md

## Workflow follow-up

- After 4 weeks of use, check the success metric on the Status page; the human archives the change.
