# Spec Delta

## Purpose

Proactive help beyond briefs: prioritising mail, drafting replies, nudges, task drafts and
delegation, protecting focus and keeping work aligned with the owner's goals — following proven
practices (GTD, Eisenhower, Covey, Newport, Grove, Drucker, McKeown; docs/research/proactive-assistance.md).

## ADDED Requirements

### Requirement: Propose, never act alone
Every outward action (saving an email draft, creating a ClickUp task) SHALL wait in the approval queue until the owner approves it; the system SHALL never send email, never write to Telegram, and never act on a suggestion that was not approved.

#### Scenario: Nothing is sent
- **WHEN** the owner approves an email reply draft
- **THEN** it is saved as a draft in the original Gmail thread and is not sent

### Requirement: Approval queue
The Assistant page SHALL list pending suggestions (reply drafts, nudges, task drafts, delegation and decline suggestions) with the reason, the sources and the goal they serve, and SHALL offer approve, edit then approve, and discard with an optional reason.

#### Scenario: Edit before approving
- **WHEN** the owner edits a task draft's due date and approves it
- **THEN** the task is created with the edited due date

### Requirement: Email priority with reasons
Needs-reply and important email SHALL be ordered by importance (who the sender is to the owner, link to a confirmed goal, money or contract, explicit deadline) and urgency (deadline, waiting time), and each SHALL show its quadrant (do now, schedule, delegate, drop) and the reason.

#### Scenario: Goal-linked mail first
- **WHEN** two emails need a reply and one concerns a confirmed 2026 Quokka goal
- **THEN** that email is listed first with the reason "Quokka goal: marketplace launch"

### Requirement: Reply drafts
For the top needs-reply emails (default 10 per day) the system SHALL draft a reply in the language of the thread and the owner's tone (learned from the owner's sent mail), using knowledge-base context with cited sources; approved drafts SHALL be saved to the email account's drafts in the same thread. For Telegram, drafts SHALL be shown for copying with a link that opens the chat.

#### Scenario: Draft with context
- **WHEN** a dealer asks about delivery terms that were agreed in an earlier thread
- **THEN** the draft states those terms and cites the earlier thread

#### Scenario: Telegram draft
- **WHEN** the owner opens a Telegram reply draft
- **THEN** it can be copied and the chat opened in Telegram; nothing is sent by the system

### Requirement: Two-minute items and nudges
Items answerable in a couple of minutes SHALL be grouped as "do now" in the mail revision; promises owed to the owner that are overdue SHALL get a short, polite nudge draft.

#### Scenario: Overdue promise to the owner
- **WHEN** customs documents promised to the owner are 2 days overdue
- **THEN** a nudge draft to that person is waiting in the approval queue

### Requirement: Delegation and decline suggestions
When a request matches a teammate's area (by their ClickUp lists and past tasks), the system SHALL suggest delegating it as a ClickUp task draft; when a new commitment serves no confirmed goal and the week is overloaded, it SHALL suggest declining or deferring, with a polite draft.

#### Scenario: Delegable request
- **WHEN** an email asks to update product photos for a marketplace
- **THEN** a task draft assigned to the teammate who handles listings is suggested

### Requirement: Focus protection
The morning brief SHALL show today's free focus blocks (90 minutes or longer, from the calendar) and suggest which priority to work on in each; when meetings take more than half of the working hours of a day, the brief SHALL warn.

#### Scenario: Meeting-heavy day
- **WHEN** meetings fill 5 of 8 working hours tomorrow
- **THEN** the evening wrap warns and suggests which meeting could be shortened or moved

### Requirement: Goal alignment and attention audit
The weekly plan SHALL propose up to 5 priorities ("big rocks") per week drawn from confirmed goals and open loops; the weekly review SHALL show where attention went (messages, meetings and tasks per area) compared with the goals, and list goals without activity for two weeks.

#### Scenario: Neglected goal
- **WHEN** a confirmed personal goal had no related activity for two weeks
- **THEN** the weekly review lists it under "no progress" with a suggested first step

### Requirement: Decision log
Decisions found in conversations and meetings SHALL be listed with date, people and source per area, and included in the weekly review.

#### Scenario: Decisions of the week
- **WHEN** the weekly review runs
- **THEN** it lists the week's decisions per area, each linked to its source

### Requirement: Learning from corrections
Edits and discards SHALL be recorded and used for later suggestions (tone examples, sender preferences, priority reasons); the acceptance rate of each suggestion kind SHALL be shown on Status.

#### Scenario: Repeated discards
- **WHEN** the owner discards decline suggestions five times in a row
- **THEN** Status shows the low acceptance and decline suggestions become less frequent
