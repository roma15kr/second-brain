# Spec Delta

## Purpose

The assistant prepares work (mail drafts, tasks, comments) and the owner only moderates it;
texts are short; only what concerns the owner and the owner's team reaches the owner.

## ADDED Requirements

### Requirement: Reply drafts are saved to the mailbox
For each email thread that needs the owner's reply (the last message is from a person to the owner, asks or expects an answer, and is not a newsletter, notification or CC-only), the system SHALL write a reply draft in the thread's language and the owner's tone and save it to that mailbox's Drafts in the same thread, without sending it. Only mail that arrives after the feature is switched on SHALL be considered; a thread SHALL get at most one draft, and a draft the owner deleted SHALL not be recreated.

#### Scenario: Dealer asks about prices
- **WHEN** a dealer writes "Can you confirm the October prices?" to the owner's quokka mailbox
- **THEN** within the next cycle a reply draft appears in Gmail Drafts in that thread and nothing is sent

#### Scenario: Not every email
- **WHEN** a newsletter, a notification or a CC-only thread arrives
- **THEN** no draft is created

#### Scenario: Owner deleted the draft
- **WHEN** the owner deletes a proposed draft in Gmail
- **THEN** the system does not create another draft for that thread unless a new message arrives

### Requirement: Meeting proposals are moderated in one list
For each processed meeting the system SHALL produce a summary of at most 5 lines and proposals: new ClickUp tasks (title, assignee from the owner's team or the owner, due date when stated) and comments on existing ClickUp tasks that the meeting discussed. The owner SHALL see all open proposals in one Moderate list, select any of them and create the selected ones in one action; unselected ones SHALL be discarded when the owner confirms, and nothing SHALL be created in ClickUp without that action.

#### Scenario: Weekly with Nastya
- **WHEN** a meeting decides "Nastya updates the bundle page by Friday" and discusses the existing task "Bundles redesign"
- **THEN** the Moderate list shows a task "Update the bundle page" for Anastasiya Tarasova due Friday and a comment for "Bundles redesign"

#### Scenario: Owner picks two of four
- **WHEN** the owner selects two proposals and taps "Create selected"
- **THEN** exactly those two are created in ClickUp and the other two disappear

### Requirement: The owner's team
The owner SHALL set "My team" in Settings (default: Anastasiya Tarasova, Kate Oleksyuk, Bogdan Stetsenko, Galyna Tkachenko); the team SHALL be used for mentions and assignments that notify the owner, for delegation suggestions and for meeting task assignees, matched to ClickUp members and People by name or email.

#### Scenario: Team mention
- **WHEN** a ClickUp comment mentions Kate Oleksyuk on a task the owner follows
- **THEN** it is listed for the owner like a mention of the owner's team

### Requirement: Daily planning shows only what concerns the owner's team
In the ClickUp channel `#dailyplanning`, only posts that mention the owner or a team member, or are written by a team member, SHALL reach briefs, loops, pushes and proposals; all posts SHALL stay searchable.

#### Scenario: Other department's report
- **WHEN** a warehouse colleague posts a daily report mentioning only their own manager
- **THEN** it is searchable but does not appear in the brief, loops or proposals

#### Scenario: Report for the owner
- **WHEN** Bogdan Stetsenko posts "@Roman Сьогодні: …"
- **THEN** it is included in the owner's daily summary of the team

### Requirement: Texts are short
Briefs SHALL have at most 8 lines with only items that need the owner's action or attention; summaries of meetings and threads SHALL have at most 5 lines.

#### Scenario: Quiet morning
- **WHEN** nothing needs the owner's action
- **THEN** the morning brief is one line saying so
