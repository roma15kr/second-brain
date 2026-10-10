# Spec Delta

## Purpose

Labels every piece of knowledge with the part of the owner's life it belongs to — Personal, Digisoft,
Quokka or RDIM — so searches can be narrowed and ended engagements can be frozen.

## ADDED Requirements

### Requirement: Every item has at least one scope or is unsorted
The system SHALL assign each ingested item one or more of the scopes `personal`, `digisoft`, `quokka`, `rdim`, or mark it `unsorted` when no scope can be determined with confidence.

#### Scenario: Item always labelled
- **WHEN** any item becomes searchable
- **THEN** it carries at least one scope or the `unsorted` label

### Requirement: Configured rules decide first
The system SHALL assign scope using configured rules (by mailbox, sender/recipient domain or address, mail label, or Telegram chat) and SHALL NOT override a rule match with AI classification.

#### Scenario: Project mailbox
- **WHEN** an email arrives in the mailbox configured for Quokka
- **THEN** the email is scoped `quokka`

#### Scenario: Rule wins over AI
- **WHEN** a Telegram chat is mapped to `rdim` by rule and its content looks personal
- **THEN** its items are scoped `rdim`

### Requirement: AI classification is the fallback
For items no rule matches, the system SHALL classify scope with AI; results below the confidence threshold SHALL be marked `unsorted`.

#### Scenario: Unmapped chat, clear topic
- **WHEN** an item from an unmapped Telegram chat clearly discusses Digisoft's Shopify store
- **THEN** it is scoped `digisoft`

#### Scenario: Ambiguous item
- **WHEN** the classifier cannot decide with confidence
- **THEN** the item is marked `unsorted`

### Requirement: Unsorted items can be reviewed and resolved
The system SHALL let the owner list unsorted items and assign a scope to an item or turn the decision into a rule for its whole chat or sender.

#### Scenario: Resolve as rule
- **WHEN** the owner assigns `quokka` to an unsorted item and chooses "apply to this chat"
- **THEN** all existing and future items from that chat are scoped `quokka`

### Requirement: Archived scopes are read-only
When a scope is marked archived, the system SHALL stop syncing sources that belong only to that scope, and SHALL keep its existing items searchable.

#### Scenario: Contract ends
- **WHEN** the owner archives the `rdim` scope
- **THEN** RDIM-only mailboxes and chats stop syncing, and earlier RDIM items still appear in search
