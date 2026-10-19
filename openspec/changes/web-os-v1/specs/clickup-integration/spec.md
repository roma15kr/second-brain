# Spec Delta

## Purpose

Brings the team's work in ClickUp into the second brain, marked per project, and lets the assistant
create tasks for the team — only after the owner approves them.

## ADDED Requirements

### Requirement: Lists are chosen and marked per project
After connecting with a personal API token, the owner SHALL choose which spaces, folders or lists to sync and mark each with a project (or personal). Unmarked lists SHALL not be synced.

#### Scenario: Quokka workspace
- **WHEN** the owner selects the Quokka space and marks it `quokka`
- **THEN** its lists' tasks are synced and scoped `quokka`

### Requirement: Tasks and comments are ingested
The system SHALL sync tasks (name, description, status, assignees, due date, list, comments) from chosen lists within 10 minutes of a change, keep them searchable like other items, and link assignees to people by email.

#### Scenario: Comment on a task
- **WHEN** a teammate comments on a Quokka task
- **THEN** within 10 minutes the comment is searchable and the task appears in the person's recent activity

### Requirement: Tasks are created only after approval
The system SHALL create a ClickUp task only from a task draft the owner approved (possibly after editing name, description, assignee, due date and list), and SHALL link the new task back to the conversation or meeting it came from. It SHALL NOT edit, close or delete existing ClickUp tasks.

#### Scenario: Approving a task draft
- **WHEN** the owner approves a task draft for Олена due Friday in list "Marketplaces"
- **THEN** the task exists in that list with the assignee, due date and a link to the source meeting

#### Scenario: Discarded draft
- **WHEN** the owner discards a task draft
- **THEN** nothing is created in ClickUp

### Requirement: ClickUp feeds loops
A loop linked to a ClickUp task SHALL close when the task is closed in ClickUp; tasks assigned to the owner and due SHALL appear in the morning brief.

#### Scenario: Task closed by the team
- **WHEN** a delegated task created from a meeting is closed in ClickUp
- **THEN** the related loop is marked done

### Requirement: Rate limits are respected
Sync SHALL stay within ClickUp's per-token rate limit and back off when told to wait, without losing changes.

#### Scenario: Limit reached
- **WHEN** ClickUp answers "too many requests"
- **THEN** sync pauses for the indicated time and resumes from where it stopped

### Requirement: Items for the owner are pushed right away
The system SHALL notify the owner by push, as soon as the next sync sees it, when a ClickUp task is assigned to the owner or to the owner's team group (default "DTC"), or a comment assigns, @mentions the owner or @mentions that group; the owner's own comments and items from before connecting SHALL NOT notify. Each item SHALL notify once, respect quiet hours, and appear in the next morning brief or evening wrap under "For you in ClickUp".

#### Scenario: Mentioned in a comment
- **WHEN** a teammate writes "@Owner can you approve the banners?" on a Quokka task
- **THEN** within minutes the owner's phone shows "ClickUp: Олена mentioned you", and tapping it opens the task in the web OS

#### Scenario: DTC team assigned
- **WHEN** a task is assigned to the DTC group
- **THEN** the owner gets one push, and a later edit of the same task does not push again

#### Scenario: Quiet hours
- **WHEN** a mention arrives at 23:30
- **THEN** no push is sent and the mention is listed in the 08:00 morning brief

### Requirement: The owner's ClickUp inbox and chats
Because ClickUp has no Inbox API, the system SHALL rebuild the owner's inbox: tasks changed anywhere in the workspace that the owner is assigned to, watches or created (or that are assigned to the owner's team group) SHALL be stored with all comments and notify like synced tasks, even when their list is not chosen for sync. Direct messages, group DMs and channels the owner follows or is a member of SHALL be read; a direct message or an @mention of the owner SHALL push right away.

#### Scenario: Mention in a list that is not synced
- **WHEN** someone @mentions the owner in a task of a list the owner did not choose for sync
- **THEN** the task is stored and searchable and the owner gets the push "mentioned you"

#### Scenario: Direct message
- **WHEN** a teammate writes to the owner in a ClickUp DM
- **THEN** the message is searchable and a push "wrote to you" arrives right away

### Requirement: The workspace has its own mark
The owner SHALL be able to mark a whole ClickUp workspace (personal or a project); the mark SHALL apply to its chats, to inbox tasks from lists without a mark, and, on request, to every list and everything stored from them.

#### Scenario: Workspace is one project
- **WHEN** the owner marks the Adducate workspace quokka and applies it to all lists
- **THEN** its tasks, comments and chats are marked quokka only, and its people show quokka only
