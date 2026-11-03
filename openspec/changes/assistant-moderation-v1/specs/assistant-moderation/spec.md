# Spec Delta

## Purpose

The assistant prepares work (mail drafts, tasks, comments) and the owner only moderates it;
texts are short; only what concerns the owner and the owner's team reaches the owner.

## ADDED Requirements

### Requirement: Reply drafts are saved to the mailbox
For each new email thread that needs the owner's reply, the system SHALL write a reply draft in the thread's language and the owner's tone and save it to that mailbox's Drafts in the same thread, without sending it. Only mail that arrives after the feature is switched on SHALL be considered.

#### Scenario: Dealer asks about prices
- **WHEN** a dealer writes "Can you confirm the October prices?" to the owner's quokka mailbox
- **THEN** within the next cycle a reply draft appears in Gmail Drafts in that thread and nothing is sent

#### Scenario: Not every email
- **WHEN** a newsletter, a notification or a CC-only thread arrives
- **THEN** no draft is created

#### Scenario: Owner deleted the draft
- **WHEN** the owner deletes a proposed draft in Gmail
- **THEN** the system does not create another draft for that thread unless a new message arrives

### Requirement: Only replies that are needed get a draft
A thread SHALL get a draft only when its last message is from a person to the owner and asks or expects an answer; newsletters, notifications and CC-only threads SHALL get none. A thread SHALL get at most one draft, and a draft the owner deleted SHALL not be recreated until a new message arrives.

#### Scenario: Bulk mail
- **WHEN** a marketplace notification arrives
- **THEN** no draft is created

### Requirement: Meeting proposals are moderated in one list
For each processed meeting the system SHALL produce a summary of at most 5 lines and proposals: new ClickUp tasks (title, assignee from the owner's team or the owner, due date when stated) and comments on existing ClickUp tasks that the meeting discussed. The owner SHALL see all open proposals in one Moderate list, select any of them and create the selected ones in one action; unselected ones SHALL be discarded when the owner confirms, and nothing SHALL be created in ClickUp without that action.

#### Scenario: Weekly with Nastya
- **WHEN** a meeting decides "Nastya updates the bundle page by Friday" and discusses the existing task "Bundles redesign"
- **THEN** the Moderate list shows a task "Update the bundle page" for Anastasiya Tarasova due Friday and a comment for "Bundles redesign"

#### Scenario: Owner picks two of four
- **WHEN** the owner selects two proposals and taps "Create selected"
- **THEN** exactly those two are created in ClickUp and the other two disappear

### Requirement: Proposals can be changed before they are created
For every proposal in the Moderate list the owner SHALL be able to (a) give an instruction, typed or dictated, after which the AI rewrites the proposal accordingly and shows the new version for moderation, or (b) edit the proposal's text, title, assignee or due date directly, typing or dictating; nothing SHALL be created until the owner approves the changed version.

#### Scenario: AI revision by voice
- **WHEN** the owner dictates "make it shorter and assign it to Kate, due Monday" on a proposed task
- **THEN** the task shows a shorter title, Kate Oleksyuk as assignee and next Monday as due date, still waiting for approval

#### Scenario: Own wording
- **WHEN** the owner replaces the text of a proposed ClickUp comment with their own words
- **THEN** exactly that text is posted when the owner creates it

### Requirement: Task proposals can be merged
The owner SHALL be able to select two or more task proposals and merge them into one proposal, optionally saying how (typed or dictated); the merged task SHALL keep every concrete point of the originals, replace them, and wait for approval. The assistant SHALL see the proposals waiting in Moderate and SHALL be able to list, merge and change them on request.

#### Scenario: One SEO task from three
- **WHEN** the owner selects the first three task proposals from "Weekly Kate" and merges them
- **THEN** one task proposal with all three points replaces them in Moderate

#### Scenario: Asked in the assistant
- **WHEN** the owner asks the assistant "make one task from the first three proposals of Weekly Kate"
- **THEN** the assistant finds those proposals and prepares the merged task for approval

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
