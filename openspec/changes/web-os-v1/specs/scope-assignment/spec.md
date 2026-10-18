# Spec Delta

## Purpose

Marking things as Personal or a project happens in the web OS, and the owner can add projects.

## MODIFIED Requirements

### Requirement: Every item has at least one scope or is unsorted
The system SHALL assign each ingested item one or more scopes — `personal` or one of the owner's projects (initially `digisoft`, `quokka`, `rdim`) — or mark it `unsorted` when no scope can be determined. The owner SHALL be able to add a project and archive or rename it in the web OS.

#### Scenario: Item always labelled
- **WHEN** any item becomes searchable
- **THEN** it carries at least one scope or the `unsorted` label

#### Scenario: New project
- **WHEN** the owner adds a project "acme" for a new client
- **THEN** `acme` can be used to mark mailboxes, dialogs, ClickUp lists, calendars and documents, and as a search filter

### Requirement: Unsorted items can be reviewed and resolved
The system SHALL let the owner, in the web OS or on the command line, list unsorted items and assign a scope to an item, or turn the decision into a rule for its whole chat, sender, sender domain, ClickUp list or calendar. Marks set on the Connectors page (per mailbox, dialog, list or calendar) SHALL act as rules and re-scope existing items.

#### Scenario: Resolve as rule
- **WHEN** the owner assigns `quokka` to an unsorted item and chooses "apply to this chat"
- **THEN** all existing and future items from that chat are scoped `quokka`

#### Scenario: Re-marking a dialog
- **WHEN** the owner changes a Telegram dialog's mark from `personal` to `rdim`
- **THEN** its existing and future conversations are scoped `rdim`
