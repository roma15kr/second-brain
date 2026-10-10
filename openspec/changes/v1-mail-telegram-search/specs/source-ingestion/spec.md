# Spec Delta

## Purpose

Brings the owner's mailboxes and chosen Telegram chats into the knowledge base, continuously and with a
12-month history, while keeping an unchanged copy of everything fetched.

## ADDED Requirements

### Requirement: Configured mailboxes are ingested
The system SHALL ingest every mailbox listed in configuration, whether Gmail/Google Workspace or a generic IMAP server, including messages in all folders/labels except those excluded by configuration (spam and trash are excluded by default).

#### Scenario: New mail arrives
- **WHEN** a new email is delivered to a configured mailbox
- **THEN** it is searchable by exact words within 5 minutes

#### Scenario: Spam is not ingested
- **WHEN** an email is in the spam or trash folder
- **THEN** it is not ingested

### Requirement: Only allowlisted Telegram chats are ingested
The system SHALL read Telegram through the owner's own account and ingest only chats (direct messages, groups, forum topics, channels) on the allowlist. It SHALL never send messages, mark them read or change anything in Telegram.

#### Scenario: Allowlisted chat message
- **WHEN** a message is posted in an allowlisted chat
- **THEN** it is searchable by exact words within 2 minutes

#### Scenario: Chat not on the allowlist
- **WHEN** a message is posted in a chat that is not allowlisted
- **THEN** nothing from that chat is stored

#### Scenario: Reading leaves no trace
- **WHEN** the system ingests unread messages
- **THEN** they remain unread in the owner's Telegram apps

### Requirement: Edits and deletions are reflected
The system SHALL update the searchable content when a Telegram message is edited, and SHALL hide a message from search when it is deleted at the source, while keeping the archived copy.

#### Scenario: Message edited
- **WHEN** an ingested Telegram message is edited
- **THEN** search returns the edited text and not the old text

#### Scenario: Message deleted
- **WHEN** an ingested Telegram message is deleted in Telegram
- **THEN** it no longer appears in search results

### Requirement: Twelve-month backfill
When a source is first added, the system SHALL ingest its history for the preceding 12 months (configurable per source), without blocking ingestion of new data.

#### Scenario: Adding a mailbox
- **WHEN** a mailbox is added to configuration
- **THEN** emails from the last 12 months become searchable, and new mail is ingested while the backfill is still running

### Requirement: Lossless archive
The system SHALL keep an unchanged copy of everything fetched from each source, including items older than the indexing window, so that all search data can be rebuilt without fetching again.

#### Scenario: Rebuild from archive
- **WHEN** the owner runs a rebuild for a source
- **THEN** that source's searchable content is regenerated from the archive with no calls to the source

### Requirement: Ingestion is idempotent and resumable
The system SHALL never create duplicates when the same data is fetched more than once, and SHALL resume from where it stopped after a restart or outage.

#### Scenario: Restart during backfill
- **WHEN** the service restarts in the middle of a backfill
- **THEN** the backfill continues from its last position and no item is duplicated

### Requirement: Sync health is visible
The system SHALL report, per source, the last successful sync time, backlog size and last error, and SHALL flag a source as unhealthy when it has not synced within 3 times its schedule interval or its credentials stop working.

#### Scenario: Expired credentials
- **WHEN** a mailbox's credentials are revoked or expire
- **THEN** the source is reported unhealthy with an error naming the credential problem
