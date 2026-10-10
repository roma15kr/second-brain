# Spec Delta

## Purpose

Exposes the knowledge base to Claude Code, Claude Desktop and other MCP clients as simple, fast,
predictable tools; the client does the reasoning and writes the answer.

## ADDED Requirements

### Requirement: Retrieval tools
The MCP server SHALL provide: `search` (all sources), `search_mail`, `search_chats` (Telegram), `get_item` (full conversation by id), `recent_activity` (latest conversations by scope/person/source/time), and `person` (person lookup).

#### Scenario: Tool discovery
- **WHEN** an MCP client lists tools
- **THEN** the six tools are listed, each with a description of what it is good for and its parameters

### Requirement: Tools return evidence, not answers
Tools SHALL return structured evidence (as defined by knowledge search) and SHALL NOT generate a free-text answer; no server-side AI call is made at query time.

#### Scenario: No AI cost per query
- **WHEN** the client calls `search`
- **THEN** the response contains ranked results and no external AI service is called to produce it

### Requirement: Full conversation retrieval
`get_item` SHALL return the full (redacted) conversation for an item id, with message authors, timestamps and enrichment, paginated for long conversations.

#### Scenario: Open a long thread
- **WHEN** the client calls `get_item` for a 300-message conversation
- **THEN** it receives the first page and a cursor to fetch the rest

### Requirement: Clear errors
Invalid parameters or unknown ids SHALL produce an error message that says what was wrong and what values are accepted.

#### Scenario: Unknown scope
- **WHEN** the client passes scope `acme`
- **THEN** the error lists the valid scopes

### Requirement: Private access only
The MCP server SHALL be reachable only from the owner's private network and SHALL require a token on every request.

#### Scenario: Request without token
- **WHEN** a request arrives without a valid token
- **THEN** it is rejected and no data is returned

#### Scenario: Public internet
- **WHEN** someone tries to reach the MCP server from the public internet
- **THEN** the connection is not accepted
