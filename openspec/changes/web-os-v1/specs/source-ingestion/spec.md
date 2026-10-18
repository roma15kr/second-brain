# Spec Delta

## Purpose

Sources (mailboxes, Telegram dialogs) are chosen and marked in the web OS instead of only in the
server configuration.

## MODIFIED Requirements

### Requirement: Configured mailboxes are ingested
The system SHALL ingest every mailbox connected in the web OS or listed in configuration over IMAP with an app password, including messages in all folders/labels except those excluded (spam, trash and drafts are excluded by default). For Gmail it SHALL read the All Mail folder once, keep Gmail's thread ids and labels, and never mark messages read. Drafts saved by the assistant SHALL never be ingested as messages from the owner.

#### Scenario: New mail arrives
- **WHEN** a new email is delivered to a connected mailbox
- **THEN** it is searchable by exact words within 5 minutes

#### Scenario: Mailbox added in the web OS
- **WHEN** the owner connects a second mailbox on the Connectors page with a valid app password
- **THEN** its new mail and its 12-month history are ingested without a server restart or configuration change

#### Scenario: Gmail labels and sent mail
- **WHEN** the owner sends a reply from Gmail or a message carries a Gmail label
- **THEN** the sent message is ingested into the same thread and the label can be used in scope rules

#### Scenario: Spam is not ingested
- **WHEN** an email is in the spam or trash folder
- **THEN** it is not ingested

#### Scenario: Assistant draft is not a reply
- **WHEN** an approved reply draft is saved to Gmail Drafts but not sent
- **THEN** the thread's needs-reply loop stays open

### Requirement: Only allowlisted Telegram chats are ingested
The system SHALL read Telegram through the owner's own account and ingest only chats (direct messages, groups, forum topics, channels) the owner has included, on the Connectors page or in configuration. New dialogs SHALL never be included automatically; they SHALL be listed for the owner to include or ignore. The system SHALL never send messages, mark them read or change anything in Telegram.

#### Scenario: Allowlisted chat message
- **WHEN** a message is posted in an included chat
- **THEN** it is searchable by exact words within 2 minutes

#### Scenario: Chat not on the allowlist
- **WHEN** a message is posted in a chat that is not included
- **THEN** nothing from that chat is stored

#### Scenario: Including a dialog from the web OS
- **WHEN** the owner includes a dialog and marks it `quokka` on the Connectors page
- **THEN** its messages (with 12-month history) are ingested and scoped `quokka` within 5 minutes, without a restart

#### Scenario: Reading leaves no trace
- **WHEN** the system ingests unread messages
- **THEN** they remain unread in the owner's Telegram apps
