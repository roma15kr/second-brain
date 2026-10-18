# Spec Delta

## Purpose

Turns raw messages into conversation-sized units that can be found by what they are about — enriched
with a summary, the question they answer and their outcome — plus individually findable key passages.

## ADDED Requirements

### Requirement: Email is indexed per thread
The system SHALL treat a whole email thread as one searchable unit, and SHALL refresh that unit (content, participants, last activity) when any new message joins the thread.

#### Scenario: Reply arrives
- **WHEN** a reply is added to an existing email thread
- **THEN** search returns one result for the thread, showing the new reply and the updated last-activity time

### Requirement: Telegram is indexed per conversation
The system SHALL group Telegram messages into conversations: a reply chain or forum topic forms one conversation; otherwise consecutive messages in a chat form one conversation until a configurable silence gap (default 45 minutes).

#### Scenario: Silence splits conversations
- **WHEN** two messages in a direct chat are 3 hours apart with no reply link
- **THEN** they belong to different conversations

#### Scenario: Late reply joins its conversation
- **WHEN** a message replies to a message from yesterday
- **THEN** it is indexed with yesterday's conversation

### Requirement: Conversations are enriched
The system SHALL generate for each conversation: a one-line question it answers, a short summary, its outcome or decision (if any), and mentioned entities (people, companies, products, amounts, dates), in the conversation's dominant language.

#### Scenario: Paraphrased question finds conversation
- **WHEN** a conversation discussed moving a launch because of a supplier delay, without using the word "postpone"
- **THEN** a search for "why was the launch postponed" returns it in the top 10

### Requirement: Key passages are findable on their own
The system SHALL also index qualifying runs of consecutive messages by one author as separate passages carrying their conversation's topic, when they contain rare terms and enough content (or received reactions).

#### Scenario: Detail buried in a long thread
- **WHEN** a 60-message group conversation contains one message with a specific tracking number and delivery explanation not reflected in the summary
- **THEN** searching for that explanation returns the passage, linked to its conversation

#### Scenario: Filler not indexed as passage
- **WHEN** a run of messages is only "ok thanks 👍"
- **THEN** it is not indexed as a separate passage

### Requirement: Exact search is immediate; enrichment follows
Exact-word search SHALL work as soon as a message is ingested; enrichment SHALL complete within 30 minutes of a conversation going quiet.

#### Scenario: Fresh message
- **WHEN** a message was ingested 1 minute ago
- **THEN** it can be found by an exact word it contains, even before enrichment

### Requirement: Mixed-language content is supported
The system SHALL index and search Ukrainian, Russian and English content, including conversations that mix them.

#### Scenario: Cross-language match
- **WHEN** a conversation in Ukrainian discusses an invoice and the owner searches in English for "invoice from the printing house"
- **THEN** the conversation is returned in the top 10
