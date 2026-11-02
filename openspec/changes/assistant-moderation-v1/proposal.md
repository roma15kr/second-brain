# Proposal: assistant-moderation-v1 — prepare, don't narrate; the owner moderates

Branch: `change/assistant-moderation-v1`, from `main`.

## Why

**Problem (owner, 2026-11-02):** "You are preparing a lot of texts — I have no time to read them
all. Analyze mail and propose answers only where necessary — save them as drafts; I'll moderate.
When you summarize meetings — propose tasks (or comments) that I moderate and choose which to
create. I'm the head of the DTC team: Anastasiya Tarasova, Kate Oleksyuk, Bogdan Stetsenko,
Galyna Tkachenko. Don't moderate daily planning entirely — just mentions for my team and me."

**Evidence:** reply drafts today wait in the web OS approval queue and need a tap before they reach
Gmail; briefs and meeting summaries are long; `#dailyplanning` (≈ 25 people post daily reports) is
read in full; the team is taken from a ClickUp group that may not match the owner's real team.

**Success metric:** the owner opens the web OS ≤ 1 time a day for moderation (one list) and
≥ 70% of proposed drafts/tasks are kept (measured on Status over 2 weeks).

## What Changes

- **Mail:** for emails that really need the owner's answer (needs-reply, from a person, not
  newsletters/notifications/CC-only), a reply draft is written and **saved straight into that
  mailbox's Gmail/IMAP Drafts in the thread** — never sent. Only new mail (owner, 2026-11-02: no backfill). The
  owner edits or deletes it in Gmail; a draft the owner deleted is not recreated.
- **Meetings:** each processed meeting yields a short summary (≤ 5 lines) and **proposals**: new
  ClickUp tasks (title, assignee from the team, due date) and **comments on existing ClickUp tasks**
  the meeting discussed. One "Moderate" list in the web OS: tick what to create → "Create
  selected"; the rest is discarded.
- **My team:** Settings → "My team" (default: the four DTC people above) replaces the ClickUp group
  as the owner's team for mentions, assignments, delegation and meeting task assignees.
- **#dailyplanning:** stays searchable, but only posts that mention the owner or the team (or are
  written by the team) reach briefs, loops, pushes and proposals.
- **Shorter texts everywhere:** briefs ≤ 8 lines, summaries ≤ 5 lines, no section without action.

## Capabilities

### New Capabilities
- `assistant-moderation`: Gmail drafts for needed replies, meeting proposals (tasks and comments)
  with one moderation list, the owner's team, the daily-planning filter, short texts.

### Modified Capabilities
None in `openspec/specs/` (reply drafts, meeting processing and ClickUp live in the unarchived
`web-os-v1` change; this change supersedes "approved drafts are saved" with "drafts are saved").

## Impact

- Server: `assistant/drafting.py` (selection, IMAP APPEND to Drafts), `recordings.py` (proposals),
  `connectors/clickup.py` (team, channel filter, comment creation), briefs prompts, settings.
- Web: Moderate list, Settings → My team.
- No new dependencies.
