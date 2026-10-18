# secret-redaction Specification

## Purpose

Prevents credentials and payment secrets found in mail and chats from ever being sent to external AI
services, while the original stays on the owner's server.

## Requirements

### Requirement: Secrets are redacted before leaving the server
Before any text is sent to an external AI service, the system SHALL replace hard secrets with a typed placeholder: passwords next to login context, payment card numbers, IBAN and bank account numbers, one-time/verification codes, API keys, access tokens and private keys.

#### Scenario: Password in a chat
- **WHEN** a Telegram message reads "login: admin, password: Zx9!qq2L"
- **THEN** text sent to the AI service contains `[REDACTED:password]` instead of the password

#### Scenario: Card number in an email
- **WHEN** an email contains a valid payment card number
- **THEN** text sent to the AI service contains `[REDACTED:card]` instead of the number

#### Scenario: Ordinary numbers kept
- **WHEN** a message contains a phone number, a price, an order number or a date
- **THEN** it is not redacted

### Requirement: Search results do not expose redacted secrets
Results returned through the MCP tools SHALL contain the redacted form of the text.

#### Scenario: Searching an OTP message
- **WHEN** the owner searches for "verification code" and a matching message contains a one-time code
- **THEN** the result shows `[REDACTED:otp]` and not the code

### Requirement: The original is preserved locally
The system SHALL keep the unredacted original in the local archive only.

#### Scenario: Archive keeps original
- **WHEN** a message with a redacted secret is ingested
- **THEN** the archive on the server holds the original text unchanged
