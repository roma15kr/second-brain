# knowledge-search Specification

## Purpose

Finds the most relevant evidence across all indexed sources for a natural-language or exact query,
and returns it in a form an AI client can cite.

## Requirements

### Requirement: Hybrid ranking
Search SHALL rank results by combining exact-word matching, meaning-based matching and term rarity, so that each method compensates for the others' blind spots.

#### Scenario: Exact string wins
- **WHEN** the query is an exact error message, order number or email address that appears verbatim in one item
- **THEN** that item is the first result

#### Scenario: Meaning without shared words
- **WHEN** the query and the relevant conversation share no words but have the same meaning
- **THEN** the conversation is in the top 10

#### Scenario: Short filler does not rank
- **WHEN** many items consist of "sounds good, thanks"
- **THEN** none of them outrank an item containing a rare term from the query

### Requirement: Recency breaks ties
When two results are otherwise similarly relevant, search SHALL rank the more recent one higher; recency SHALL only adjust, never dominate, relevance.

#### Scenario: Two answers to one question
- **WHEN** two conversations answer the same question, one from last week and one from 10 months ago
- **THEN** last week's ranks higher

### Requirement: Results are diverse and deduplicated
Search SHALL return at most one result per conversation by default, showing the best-matching part, and SHALL return 10 results by default (maximum 50).

#### Scenario: Passage and its conversation both match
- **WHEN** both a conversation and a passage inside it match the query
- **THEN** a single result is returned for that conversation

### Requirement: Filters
Search SHALL support filtering by scope(s), source (mail/Telegram), mailbox or chat, person, and date range. Unsorted items SHALL be included unless the scope filter excludes them.

#### Scenario: Scope filter
- **WHEN** the owner searches with scope `quokka`
- **THEN** only items scoped `quokka` are returned

#### Scenario: Person and date filter
- **WHEN** the owner searches with person "Oleh" and dates in September 2026
- **THEN** only items involving Oleh within that range are returned

### Requirement: Cited evidence with context
Each result SHALL include: source, scope(s), title or subject, participants, date of the matched message and last activity, the summary, the matched excerpt with neighbouring messages for context, a stable item id, and a deep link to open the original where the source supports it (Gmail web search link for Gmail, t.me link for Telegram chats that have one).

#### Scenario: Result is citable
- **WHEN** a result is returned
- **THEN** it contains an item id that `get_item` can open and a link or locator to the original message

### Requirement: Response time
Search SHALL return results within 3 seconds at the median and 8 seconds at the 95th percentile for the v1 data volume.

#### Scenario: Typical query
- **WHEN** a typical query runs over 12 months of mail and Telegram
- **THEN** results return within 3 seconds
