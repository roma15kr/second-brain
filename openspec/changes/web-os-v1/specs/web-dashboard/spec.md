# Spec Delta

## Purpose

The second brain OS itself: an app shell with a dock, command palette and notification center, and
the pages through which the owner works with briefs, mail, loops, conversations, people, scopes and
system health, on desktop and phone (mockups in `mockups/`).

## ADDED Requirements

### Requirement: OS shell
Every page SHALL show a dock of apps (Today, Inbox, Briefs, Week, Loops, Search, People, Scopes, Status, Settings), a command palette (⌘K / Ctrl+K, or a search button on phones) that finds people, conversations, briefs and commands, and a notification center with unread routine notifications. On narrow screens the dock SHALL become a bottom bar.

#### Scenario: Jump to a person
- **WHEN** the owner presses ⌘K and types "Вячеслав"
- **THEN** his person page is offered and opens with Enter

#### Scenario: Phone layout
- **WHEN** the app is opened on a phone
- **THEN** the dock is a bottom bar and pages are a single column

### Requirement: Today page
Today SHALL show the latest morning brief (or evening wrap after 19:00) at the top, needs-reply items, promises due today and overdue, per-scope activity for the last 24 hours, the next scheduled routines, and a one-line system health and AI-spend indicator.

#### Scenario: Morning
- **WHEN** the owner opens Today at 08:05
- **THEN** the 08:00 brief, its needs-reply items and today's due promises are visible without scrolling on a laptop

### Requirement: Inbox page (mail revision)
Inbox SHALL show the latest revision pass grouped into needs reply, important, FYI and noise, each item with scope, sender, one-line summary, suggested action and actions: open in Gmail, done, snooze, change scope, mark sender as noise or important.

#### Scenario: Clearing the inbox
- **WHEN** the owner marks a needs-reply item done
- **THEN** it leaves the needs-reply group and the related loop closes

### Requirement: Briefs and Week pages
Briefs SHALL list every routine output by date with type filters and opened state; a brief page SHALL show its sections with source links and a usefulness rating. Week SHALL show the Friday review and the Monday plan for a selected week, with accept/edit for the plan.

#### Scenario: Last Friday's review
- **WHEN** the owner opens Week and selects last week
- **THEN** that week's review and plan are shown

### Requirement: Loops page
Loops SHALL list loops with direction, counterpart, due date or age, scope and source, with done, snooze, dismiss and due-date actions and the filters defined for open loops.

#### Scenario: Acting from the list
- **WHEN** the owner snoozes a loop from the Loops page
- **THEN** it disappears from the open list until the snooze date

### Requirement: Search and Conversation pages
Search SHALL offer the existing knowledge-base search (words and meaning, uk/ru/en) with scope, source, person and date filters, showing summaries, matched-message context and deep links. Conversation SHALL show the summary, outcome, people, scope (editable), related loops and the messages with paging and a link to the original.

#### Scenario: From result to source
- **WHEN** the owner opens a search result
- **THEN** the conversation page shows the matched message highlighted and a link opening it in Gmail or Telegram

### Requirement: People, Person and Scope pages
People SHALL list people by recent activity with channels, scopes and open loops; Person SHALL show identities, scopes, first/last interaction, open loops with them and recent conversations, with link, merge and undo-merge actions. Scope SHALL show a scope's weekly activity, open loops, key people and latest decisions, and allow archiving the scope.

#### Scenario: Merge from the UI
- **WHEN** the owner merges two "Hostinger" people on the People page
- **THEN** one person remains with all identities, and the merge can be undone from the person page

### Requirement: Settings and Status pages
Settings SHALL edit routine times and passes, quiet hours, push per device and per routine, owner identities, passkeys and recovery codes, scope rules and unsorted review, and the monthly AI budget cap. Status SHALL show source sync health, routine runs, index queue, backups, AI spend, and the usefulness metric (briefs opened/acted on, loops resolved) for the last 4 weeks.

#### Scenario: Usefulness visible
- **WHEN** the owner opens Status
- **THEN** the share of briefs opened or acted on and of loops resolved over the last 4 weeks is shown

### Requirement: Usage events are recorded
The app SHALL record when a brief is opened and when an item is acted on (open source, done, snooze, dismiss, rating), to compute the success metric; nothing is sent to third parties.

#### Scenario: Opening from a push
- **WHEN** the owner opens a brief from a notification
- **THEN** the brief is recorded as opened
