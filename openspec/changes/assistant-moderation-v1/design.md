# Design: assistant-moderation-v1

## Decisions
- **D1 Drafts go to the mailbox.** `drafting.cycle` picks needs-reply threads (triage class
  `needs_reply`, last message from a person, owner in To, not bulk headers / no-reply / CC-only),
  writes the draft as today, and saves it with the existing Save-to-Drafts executor (IMAP APPEND,
  `In-Reply-To`/`References`) instead of waiting in the approval queue. One draft per thread
  (`suggestions` row with status `saved`, mailbox UID of the draft). If the draft UID is gone on the
  next cycle (owner deleted or sent it) the thread is done until a new message arrives. No backfill:
  only messages after `drafts_since` (set when the change is deployed).
  The daily cap (Settings) still applies (default 10).
- **D2 Meeting proposals.** Meeting processing returns `tasks[]` and `comments[]` (comment:
  existing ClickUp task found by search over the meeting's scope, text). Both become suggestions of
  kind `clickup_task` / `clickup_comment` grouped by meeting. Web: Moderate page (all open
  suggestions grouped by source, checkboxes, "Create selected" / "Discard the rest").
- **D3 Team** = `app_settings.team` (names/emails); resolved to ClickUp member ids and People ids at
  sync; replaces the ClickUp group for "team" matching (the group stays as a fallback when empty).
- **D4 #dailyplanning filter**: a per-channel rule `mentions_only` (default on for channels named
  `dailyplanning`): posts without a mention of owner/team and not authored by the team get
  `metadata.ignore_for_assistant = true`; briefs, loop detection, pushes and proposals skip them.
- **D5 Short texts**: prompt limits plus a server-side trim (lines / bullets) before storing.
