# Spec Delta

## Purpose

Runs the owner's day and week on a schedule: a morning brief, mail revision passes, an evening wrap,
a Friday weekly review and a Monday weekly plan, each grounded in the owner's own mail and chats and
delivered as a page plus a push notification.

## ADDED Requirements

### Requirement: Routine schedule
The system SHALL run these routines in the owner's time zone (default Europe/Kyiv): morning brief daily 08:00, mail revision passes daily at 11:00, 14:00 and 17:00, evening wrap daily 19:00, weekly review Friday 19:00, weekly plan Monday 08:00. Times, passes and days SHALL be editable in Settings.

#### Scenario: Default day
- **WHEN** it is a Tuesday with default settings
- **THEN** a morning brief at 08:00, revisions at 11:00, 14:00 and 17:00 and an evening wrap at 19:00 are produced

#### Scenario: Changed time
- **WHEN** the owner moves the morning brief to 07:30
- **THEN** the next morning brief is produced at 07:30

### Requirement: Missed runs are caught up once
If the server was down at a scheduled time, the routine SHALL run once when the server is back (within the same day), not once per missed slot.

#### Scenario: Server down overnight
- **WHEN** the server is unavailable from 07:00 to 09:30
- **THEN** one morning brief is produced at about 09:30 and marked as delayed

### Requirement: Every statement links to its source
Every item in a brief SHALL link to the conversation it came from (opening the conversation page, with a link to the original mail or chat); briefs SHALL NOT contain claims without a source.

#### Scenario: Following a brief item
- **WHEN** the owner taps an item in a brief
- **THEN** the conversation it came from opens

### Requirement: Morning brief content
The morning brief SHALL contain: activity since the last evening wrap per scope; conversations that need the owner's reply; promises due today or overdue (by and to the owner); a suggested focus of at most 3 items; and the times of the next routines.

#### Scenario: Busy night in one scope
- **WHEN** 13 RDIM chat conversations and 1 Quokka email arrived overnight
- **THEN** the brief summarizes them per scope and lists any that need a reply

### Requirement: Mail revision passes
Each mail revision pass SHALL triage email arrived since the previous pass into needs reply, important, FYI and noise, with a one-line suggested next action for needs-reply items. A pass SHALL push a notification only if at least one needs-reply or important item exists.

#### Scenario: Quiet pass
- **WHEN** only newsletters arrived since the last pass
- **THEN** the pass is recorded with no push notification

#### Scenario: Needs reply
- **WHEN** a dealer email asking a question arrived since the last pass
- **THEN** it appears under needs reply with a suggested action and a push is sent

### Requirement: Noise learning by sender
The owner SHALL be able to mark a sender as noise or important; later passes SHALL classify that sender's mail accordingly.

#### Scenario: Always noise
- **WHEN** the owner marks a newsletter sender as noise
- **THEN** that sender's next emails are classified as noise without needing review

### Requirement: Evening wrap content
The evening wrap SHALL contain: decisions and outcomes from today's conversations, open loops opened and closed today, still-unanswered needs-reply items, and carry-overs for tomorrow.

#### Scenario: Closing the day
- **WHEN** two loops were closed and one new promise was made today
- **THEN** the wrap lists both closed loops and the new promise with its due date

### Requirement: Weekly review content (Friday)
The weekly review SHALL summarize the week per scope (key conversations, decisions, people most interacted with), list open loops by age, and show numbers (threads, chat conversations, decisions, loops opened/closed).

#### Scenario: Week across scopes
- **WHEN** the weekly review runs on Friday 19:00
- **THEN** it has a section for each scope with activity that week and omits scopes without activity

### Requirement: Weekly plan content (Monday)
The weekly plan SHALL recap the previous Monday–Sunday week and propose a plan for the coming week: loops due this week, aging loops to chase, and up to 5 suggested priorities with reasons and sources. The owner SHALL be able to accept or edit the plan; accepted priorities SHALL be referenced by the next morning briefs.

#### Scenario: Accepting the plan
- **WHEN** the owner accepts the Monday plan
- **THEN** Tuesday's morning brief shows progress on the accepted priorities

### Requirement: Briefs are kept, searchable and rated
All routine outputs SHALL be kept as pages, listed by date and type, found by search, and SHALL allow a useful / not useful rating that is recorded.

#### Scenario: Finding last month's review
- **WHEN** the owner searches for a topic covered in a weekly review a month ago
- **THEN** that weekly review is among the results

### Requirement: Usage and cost limits
Routine generation SHALL use only redacted text, record its AI cost per run, and stop generating (with a visible notice) when the monthly AI budget cap set in Settings is reached.

#### Scenario: Budget reached
- **WHEN** the monthly AI budget cap is reached
- **THEN** routines produce a short brief from data only (counts and lists without AI summaries) and Status shows that the cap was reached

### Requirement: Quiet hours
No push notifications SHALL be sent during quiet hours (default 22:00–07:30); routines inside quiet hours SHALL still produce their pages.

#### Scenario: Late routine
- **WHEN** an evening wrap is moved to 22:30
- **THEN** its page is produced and no push is sent
