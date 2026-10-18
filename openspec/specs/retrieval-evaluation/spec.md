# retrieval-evaluation Specification

## Purpose

Measures whether search finds what the owner actually looks for, so ranking changes can be judged
by numbers instead of impressions.

## Requirements

### Requirement: Question set
The owner SHALL be able to keep a file of evaluation questions, each with a query, an optional note, and what a correct result must match (item id, words in the title, words in the summary/excerpt/context, or part of the source locator).

#### Scenario: Loading questions
- **WHEN** the evaluation runs on a question file
- **THEN** every question is checked against search; an entry without a query or expectation stops the run with an error naming its position

### Requirement: Evaluation report
The evaluation SHALL run every question through search (locally or against the deployed MCP server with its token) and report recall@10, recall@1, mean reciprocal rank, median and 95th percentile latency, and every question whose answer was not found in the top 10.

#### Scenario: Against production
- **WHEN** the owner runs the evaluation with the production MCP URL
- **THEN** the report shows the metrics for the deployed system and lists each miss with its query

#### Scenario: A miss
- **WHEN** the expected item is not in the top 10 for a question
- **THEN** the question appears in the list of misses
