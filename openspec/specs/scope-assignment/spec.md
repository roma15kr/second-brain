# scope-assignment Specification

## Purpose

Labels every piece of knowledge with the part of the owner's life it belongs to — Personal, Digisoft,
Quokka or RDIM — so searches can be narrowed and ended engagements can be frozen.

## Requirements

### Requirement: Every item has at least one scope or is unsorted
The system SHALL assign each ingested item one or more of the scopes `personal`, `digisoft`, `quokka`, `rdim`, or mark it `unsorted` when no scope can be determined with confidence.

#### Scenario: Item always labelled
- **WHEN** any item becomes searchable
- **THEN** it carries at least one scope or the `unsorted` label

### Requirement: Rules decide scope, in a fixed order
The system SHALL assign scope using, in this order: rules the owner created while reviewing unsorted items, rules from configuration (by mailbox, sender/recipient domain or address, mail label or folder, or Telegram chat), the Telegram chat's configured scopes, and the source's default scopes. The first layer that matches decides. When rules change, existing items SHALL be re-scoped.

#### Scenario: Project mailbox
- **WHEN** an email arrives in the mailbox configured for Quokka
- **THEN** the email is scoped `quokka`

#### Scenario: Content does not override a rule
- **WHEN** a Telegram chat is mapped to `rdim` by rule and its content looks personal
- **THEN** its items are scoped `rdim`

#### Scenario: Nothing matches
- **WHEN** no rule, chat mapping or source default applies to an item
- **THEN** the item is marked `unsorted` (there is no AI scope classification)

#### Scenario: Rule changed
- **WHEN** the owner adds a configuration rule mapping a sender domain to `quokka`
- **THEN** existing items from that domain are re-scoped `quokka` on the next index run

### Requirement: Unsorted items can be reviewed and resolved
The system SHALL let the owner (command line) list unsorted items and assign a scope to an item or turn the decision into a rule for its whole chat or sender.

#### Scenario: Resolve as rule
- **WHEN** the owner assigns `quokka` to an unsorted item and chooses "apply to this chat"
- **THEN** all existing and future items from that chat are scoped `quokka`

### Requirement: Archived scopes are read-only
When a scope is marked archived, the system SHALL stop syncing sources that belong only to that scope, and SHALL keep its existing items searchable. Archiving SHALL be reversible.

#### Scenario: Contract ends
- **WHEN** the owner archives the `rdim` scope
- **THEN** RDIM-only mailboxes and chats stop syncing, and earlier RDIM items still appear in search
