# Spec Delta

## Purpose

One place in the web OS to connect, mark, watch and disconnect every source of the second brain,
and to see which sources are planned next.

## ADDED Requirements

### Requirement: Connector hub
The Connectors page SHALL list every connector with its state (connected, needs attention, available, planned, not possible), last successful sync, item counts per scope, and one line on what it adds to the second brain.

#### Scenario: Overview
- **WHEN** the owner opens Connectors
- **THEN** connected sources show their health and counts, and planned sources show what they will add and are not connectable

### Requirement: Connector catalog
Connectable in this change: email (Gmail, and any IMAP + SMTP mailbox), Telegram, ClickUp, calendars (Google, Apple iCloud, other CalDAV), files and notes, the owner's recorder apps and meeting notes import. Shown as planned: GitHub, Karakeep, Google Drive, Google Analytics, Meta Ads, Google Ads, TikTok Ads, marketplaces, Shopify, Stripe, password vault and ops registry. WhatsApp SHALL be shown as not possible live, with the reason and the planned chat-export import.

#### Scenario: WhatsApp explained
- **WHEN** the owner opens the WhatsApp card
- **THEN** it explains that personal WhatsApp has no official API and that chat-export import is planned

### Requirement: Connecting without the command line
The owner SHALL be able to connect email, Telegram, ClickUp and calendars from the web OS. Credentials SHALL be checked before saving, stored encrypted on the server, never shown again, and replaceable or removable.

#### Scenario: Wrong app password
- **WHEN** the owner enters a wrong app password for a mailbox
- **THEN** the page shows the server's login error and nothing is saved

#### Scenario: Secret not readable back
- **WHEN** the owner reopens a connected mailbox's settings
- **THEN** the password field shows that a password is set but not its value

### Requirement: Supported connection methods
The system SHALL support: email via Gmail (address and app password, servers preset) or any provider with IMAP and SMTP (server, port, security, user, app password; SMTP credentials may differ); Telegram via QR login on the page; ClickUp via a personal API token; calendars via Google's secret address, or Apple iCloud and other CalDAV servers with the account email and an app-specific password.

#### Scenario: Gmail preset
- **WHEN** the owner chooses Gmail and enters the address and app password
- **THEN** IMAP and SMTP are configured without entering server names

#### Scenario: Own-domain mailbox
- **WHEN** the owner connects info@digisoft.example with its IMAP and SMTP servers
- **THEN** both connections are tested, mail is ingested, and replies can be sent from that address

### Requirement: Everything is marked Personal or a project
Each connected account SHALL have a default mark (personal or a project); each mailbox rule, Telegram dialog, ClickUp list and calendar SHALL be markable on its own, overriding the default. Newly discovered dialogs, lists and calendars SHALL appear in a "to mark" list until the owner marks, includes or ignores them.

#### Scenario: New Telegram dialog
- **WHEN** someone starts a new dialog with the owner in Telegram
- **THEN** it appears under "to mark" on the Telegram connector and nothing from it is stored until included

#### Scenario: Personal mailbox
- **WHEN** the owner connects a personal Gmail account with default mark `personal`
- **THEN** its mail is scoped `personal` unless a sender rule says otherwise

### Requirement: Disconnecting
Disconnecting a source SHALL stop syncing it. The owner SHALL choose to keep its data searchable (read-only) or remove it from search; removing the archived originals SHALL require a separate confirmation.

#### Scenario: Keep history
- **WHEN** the owner disconnects RDIM's ClickUp and keeps the data
- **THEN** sync stops and earlier RDIM tasks still appear in search

### Requirement: Connector health needs attention
A connector that is unhealthy (as defined by system health) SHALL be marked "needs attention" on the hub, with the error and the action to fix it (e.g. replace the password, log in to Telegram again).

#### Scenario: Telegram logged out
- **WHEN** the Telegram session is revoked from the phone
- **THEN** the Telegram card shows "needs attention" and offers a new QR login
