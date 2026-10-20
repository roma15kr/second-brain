# Spec Delta

## Purpose

Lets the owner ask the assistant in plain language, by text or voice, from anywhere in the web OS,
and get answers with sources or prepared actions (drafts, tasks, loops, reports) that stay under
the owner's approval.

## ADDED Requirements

### Requirement: Ask from anywhere
The web OS SHALL offer a request field on every page, by text and by voice, on desktop and phone. A request SHALL accept any language the owner uses (uk/ru/en, mixed), and the answer SHALL be in the language of the request.

#### Scenario: Palette request
- **WHEN** the owner opens the command palette, chooses "Ask the assistant" and types "what did we agree with Rozetka about delivery?"
- **THEN** the request is sent and its thread opens with the answer when ready

#### Scenario: Voice request
- **WHEN** the owner taps the microphone in the request field and says "draft a task for Max to update the banners by Friday"
- **THEN** the speech is transcribed, shown in the field for checking, and sent as the request

### Requirement: Answers cite their sources
An answer that uses knowledge-base content SHALL cite the items it used, each opening the source (conversation, task, document). Statements without a source SHALL be marked as the assistant's own reasoning, and the assistant SHALL say so when it found nothing.

#### Scenario: Cited answer
- **WHEN** the owner asks "what did we agree with Rozetka about delivery?" and the terms are in an email thread
- **THEN** the answer states the terms and links to that thread

#### Scenario: Nothing found
- **WHEN** the knowledge base has nothing on the question
- **THEN** the answer says nothing was found and lists what was searched

### Requirement: Drafts and tasks go to the approval queue
Email drafts (replies or new emails), ClickUp task drafts, ClickUp comment drafts and Telegram reply drafts prepared from a request SHALL be created as suggestions in the approval queue, shown inline in the thread with approve, edit and discard. A request SHALL never send, save to a mailbox or create a task by itself.

#### Scenario: Email draft from a request
- **WHEN** the owner asks "reply to Olena that we accept the new price from November"
- **THEN** a reply draft in Olena's thread appears in the request thread and in the approval queue, and nothing is saved or sent until the owner approves it

#### Scenario: New email
- **WHEN** the owner asks "write to dealer@example.com asking for the October price list"
- **THEN** a new-email draft with that recipient appears for approval, from the mailbox the owner last used with that address or the default mailbox

#### Scenario: ClickUp comment with images
- **WHEN** the owner asks "comment in Time optimization for Bogdan to check the chart" and adds two screenshots to the draft
- **THEN** the comment is posted only after approval, assigned to Bogdan, with the screenshots attached to the task and linked in the comment

#### Scenario: Task draft
- **WHEN** the owner asks "task for Max: update the banners by Friday, Marketing list"
- **THEN** a ClickUp task draft with assignee Max, due Friday and list Marketing appears for approval

### Requirement: Open loops changed directly with undo
A request SHALL be able to create, snooze or close the owner's open loops directly, and each such change SHALL be shown in the thread with an undo.

#### Scenario: Reminder
- **WHEN** the owner says "remind me to call Olena on Thursday"
- **THEN** an open loop "Call Olena" due Thursday is created and listed in the thread with "Undo"

### Requirement: Search from a request
A request that asks to find something SHALL return the same ranked results as the Search page, with the filters it understood (project, source, person, dates) shown and editable.

#### Scenario: Search request
- **WHEN** the owner asks "find invoices from netcup this year"
- **THEN** matching items are listed with the filters "person: netcup, from: 1 January" shown

### Requirement: Reports
A request for a report SHALL produce a report page with sections and cited sources for the period, project or person asked. The owner SHALL be able to save the report to the Library as a note with a project mark.

#### Scenario: Weekly project report
- **WHEN** the owner asks "prepare a Quokka report for this week: decisions, what is late, open questions"
- **THEN** a report with those sections, each statement linked to its source, is shown and can be saved to the Library marked quokka

### Requirement: Follow-ups in a thread
Requests SHALL be kept in threads, and a follow-up SHALL use the earlier messages and results of its thread. Threads SHALL be listed newest first and kept for 90 days unless the owner pins them.

#### Scenario: Refine a draft
- **WHEN** the owner follows a task draft with "assign it to Olena instead and make it due Monday"
- **THEN** the pending task draft in the queue is updated with the new assignee and due date

### Requirement: Requests continue in the background
A request SHALL run on the server and finish even if the page is closed or the phone locks; the thread SHALL show the steps taken while it runs, and the owner SHALL get a push when a request that took longer than 30 seconds is done.

#### Scenario: Phone locked
- **WHEN** the owner sends a report request and locks the phone
- **THEN** the report is finished, a push "Report ready" arrives, and opening it shows the report

### Requirement: Privacy limits
The assistant SHALL never read Library documents marked "AI may not read", SHALL work only with redacted text, and SHALL not write to Telegram. Requests and answers SHALL be stored redacted.

#### Scenario: Private document
- **WHEN** the owner asks about content that exists only in a document marked "AI may not read"
- **THEN** the answer does not use that document and says the document is private

### Requirement: Budget
Each request SHALL count against the monthly AI budget and show its cost. When the budget is used up, a request SHALL still return plain search results for its text, and SHALL tell the owner that answers, drafts and reports need AI budget.

#### Scenario: Budget exhausted
- **WHEN** the monthly budget is used up and the owner asks for a report
- **THEN** the thread says the report needs AI budget, offers the search results instead, and shows "Run anyway", which runs this one request over the budget
