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
