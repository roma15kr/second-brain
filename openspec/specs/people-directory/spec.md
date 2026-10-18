# people-directory Specification

## Purpose

Recognises that one person writes from several email addresses and a Telegram account, so the owner
can ask about a person rather than about a handle.

## Requirements

### Requirement: People are created from correspondents
The system SHALL create a person for every distinct correspondent seen in mail or allowlisted Telegram chats, with display name(s) and identities (email addresses, Telegram user id and username, phone if shown).

#### Scenario: New sender
- **WHEN** an email arrives from an address never seen before
- **THEN** a person with that address exists

### Requirement: Identities are linked automatically when certain
The system SHALL link identities to the same person when they share an exact email address or phone number, and SHALL NOT link on name similarity alone.

#### Scenario: Same phone in Telegram and email signature
- **WHEN** a Telegram contact's phone equals the phone configured for an email contact
- **THEN** both identities belong to one person

#### Scenario: Same name, different people
- **WHEN** two correspondents are both named "Andrii" with no shared address or phone
- **THEN** they remain separate people

### Requirement: Manual merge, split and link
The system SHALL let the owner merge two people into one, undo a merge, and attach an identity (email, phone, Telegram id or username) to a person, with search reflecting the change.

#### Scenario: Merge
- **WHEN** the owner merges a Gmail correspondent with a Telegram contact
- **THEN** filtering search by that person returns items from both channels

#### Scenario: Link a phone
- **WHEN** the owner links phone `+380…` to a person
- **THEN** a Telegram contact with that phone joins that person

#### Scenario: Undo merge
- **WHEN** the owner splits a previously merged person
- **THEN** each identity again belongs to a separate person

### Requirement: Person lookup
The system SHALL return for a person: names, identities, scopes they appear in, first and last interaction, and their most recent conversations.

#### Scenario: Look up by partial name
- **WHEN** the owner looks up "Oleh"
- **THEN** all matching people are listed with enough detail to tell them apart
