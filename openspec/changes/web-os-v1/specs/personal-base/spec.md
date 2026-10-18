# Spec Delta

## Purpose

The owner's own documents — personal constitution, personal and business plans for 2026, notes and
reference files — stored in the second brain, marked Personal or a project, searchable, and used by
the assistant as the owner's goals and principles.

## ADDED Requirements

### Requirement: Documents and notes
The owner SHALL be able to upload files (Markdown, plain text, PDF, Word) up to 20 MB or write notes in the web OS. Each document SHALL have a title, a kind (constitution, plan, goals, note, reference) and a mark (personal or a project); a document cannot be saved without a mark.

#### Scenario: Uploading the business plan
- **WHEN** the owner uploads "Quokka plan 2026.pdf" as kind plan, marked `quokka`
- **THEN** it appears in the Library under Quokka with its text extracted

#### Scenario: No mark
- **WHEN** the owner tries to save a document without choosing personal or a project
- **THEN** saving is refused with a prompt to choose

### Requirement: Versions are kept
Replacing or editing a document SHALL keep earlier versions with their dates; search and the assistant SHALL use the latest version.

#### Scenario: Updated constitution
- **WHEN** the owner uploads a new version of the constitution
- **THEN** the previous version is still viewable and the assistant uses the new one

### Requirement: Documents are searchable
Documents SHALL be indexed like mail and chats (exact words and meaning, uk/ru/en, redacted) and returned by web search and the MCP tools with their mark and kind.

#### Scenario: Finding a principle
- **WHEN** the owner searches "how do I decide on new clients"
- **THEN** the relevant section of the constitution is returned

### Requirement: Core documents guide the assistant
Documents of kind constitution, plan or goals SHALL be core documents: the assistant SHALL use them for the weekly plan and review, priorities and suggestions, and SHALL cite the goal or principle it relied on. Each document SHALL have an "AI may read" switch (on for core documents, off for others by default); a document with the switch off SHALL be searchable on the server but never sent to an AI service.

#### Scenario: Private note stays local
- **WHEN** a note has "AI may read" switched off
- **THEN** it can be found by search but its text is never part of an AI request

### Requirement: Goals from plans
From core documents the system SHALL propose a list of goals (title, area or project, measure, deadline), which the owner confirms, edits or removes; only confirmed goals SHALL be used for prioritisation and reviews.

#### Scenario: Goals proposed
- **WHEN** the owner uploads the personal plan 2026
- **THEN** proposed goals appear for confirmation, each linked to the paragraph it came from
