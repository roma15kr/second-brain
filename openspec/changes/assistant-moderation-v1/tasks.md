# Tasks

## 1. Server
- [x] 1.1 Settings "My team" (default DTC four) + resolution to ClickUp members and People; team used for mentions, assignments, delegation; verify `test_team_default_and_matching`, `test_team_mention_notifies`
- [x] 1.2 #dailyplanning mentions-only filter for briefs, loops, pushes, proposals; verify `test_dailyplanning_only_team_mentions_reach_assistant`
- [x] 1.3 Reply drafts saved to the mailbox (selection rules, one per thread, deleted-not-recreated, only new mail); verify `test_needed_reply_saved_as_draft`, `test_newsletter_and_cc_get_no_draft`, `test_deleted_draft_not_recreated`
- [x] 1.4 Meeting proposals: ≤5-line summary, tasks with team assignees and dates, comments on existing tasks; create selected / discard rest API; verify `test_meeting_proposes_tasks_and_comments`, `test_create_selected_only`
- [x] 1.5 Short briefs (≤ 8 lines, one line when nothing) and summaries (≤ 5 lines); verify `test_brief_is_short`, `test_quiet_morning_one_line`

## 2. Web
- [x] 2.1 Moderate page (grouped proposals, select, create selected, discard rest) and Settings → My team; verify `Moderate.test.tsx`, `Settings.test.tsx` team case

## 2b. Changing proposals (owner 2026-11-03: "not only approve — comments for AI modification or my custom text/voice edit")
- [x] 2.2 Server: `POST /api/suggestions/{id}/revise {instruction}` (AI rewrites the editable fields: task title/description/assignee/due, comment or message text; assignee resolved to the team; revision history kept) and `PATCH /api/suggestions/{id}` (owner's own fields); verify `test_revise_task_by_instruction`, `test_owner_edit_used_on_create`
- [x] 2.3 Web: per proposal "Change with AI" (type or dictate an instruction) and "Edit" (fields, dictation into the text); verify `Moderate.test.tsx` revise and edit cases

## 3. Acceptance
- [ ] 3.1 Owner: a week of drafts in Gmail and meeting proposals moderated; share keep-rate from Status
