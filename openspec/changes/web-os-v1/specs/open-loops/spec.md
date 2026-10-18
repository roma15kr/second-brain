# Spec Delta

## Purpose

Tracks the things that are not finished yet — replies the owner owes, promises the owner made,
promises made to the owner and follow-ups — from the moment they appear in a conversation until
they are done, dismissed or snoozed.

## ADDED Requirements

### Requirement: The owner's identities are known
The owner SHALL configure which identities are "me" (email addresses, Telegram account); loop direction (owed by me / owed to me) SHALL be determined from them.

#### Scenario: Promise by the owner
- **WHEN** the owner's Telegram account writes "I'll send the price list by Monday"
- **THEN** a loop "send the price list" owed by the owner, due Monday, is created

### Requirement: Loops are detected from conversations
The system SHALL detect from new or changed conversations: (a) questions or requests to the owner still unanswered by the owner (needs reply), (b) promises by the owner, (c) promises by others to the owner, each with the counterpart person, scope, due date when stated, and a link to the message.

#### Scenario: Unanswered question
- **WHEN** a dealer emails the owner a question and the owner has not replied in that thread
- **THEN** a needs-reply loop appears for that thread

#### Scenario: Promise to the owner with a date
- **WHEN** a contact writes "I'll send the customs documents tomorrow"
- **THEN** a loop owed to the owner by that person, due the next day, appears

#### Scenario: Chit-chat is not a loop
- **WHEN** a message says "ok, thanks"
- **THEN** no loop is created

### Requirement: Loops close automatically when the conversation shows it happened
A loop SHALL be marked done when a later message in the same conversation shows it was fulfilled (the owner replied; the promised file or answer was sent), with the closing message linked.

#### Scenario: Owner replies
- **WHEN** the owner replies in a thread with an open needs-reply loop
- **THEN** that loop is marked done, linked to the reply

### Requirement: Manual actions
The owner SHALL be able to mark a loop done, dismiss it (wrong detection), snooze it until a date, change its due date, and add a loop manually; every action SHALL be recorded.

#### Scenario: Wrong detection
- **WHEN** the owner dismisses a loop as not a real promise
- **THEN** it disappears from open loops and is not recreated from the same message

#### Scenario: Snooze
- **WHEN** the owner snoozes a loop until Thursday
- **THEN** it is hidden from open loops and briefs until Thursday, then returns

### Requirement: Overdue and aging
Loops past their due date SHALL be marked overdue; loops without a due date SHALL show their age; both SHALL feed the morning brief, evening wrap and weekly routines.

#### Scenario: Overdue promise to the owner
- **WHEN** a promise to the owner was due yesterday and is not done
- **THEN** it appears as overdue in today's morning brief

### Requirement: Filtering
Loops SHALL be filterable by status (open, done, snoozed, dismissed), direction (I owe, owed to me, needs reply), scope and person.

#### Scenario: What I owe in RDIM
- **WHEN** the owner filters loops by "I owe" and scope RDIM
- **THEN** only open RDIM loops owed by the owner are shown
