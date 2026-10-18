# system-health Specification

## Purpose

Lets the owner (and AI clients) see at a glance whether the knowledge base is up to date, what it
costs, and whether the data is safely backed up and restorable.

## Requirements

### Requirement: Sync health is visible per source
The system SHALL report, per source, the last successful sync time and last error, and SHALL flag a source as unhealthy when it has not synced within 3 times its sync interval or its last sync failed.

#### Scenario: Expired credentials
- **WHEN** a mailbox's app password is revoked
- **THEN** the source is reported unhealthy with the credential error

#### Scenario: Stalled source
- **WHEN** a Telegram source has not synced for more than 3 sync intervals
- **THEN** it is reported unhealthy

### Requirement: Status report
The system SHALL provide one status report (command line and MCP `status` tool) with: overall health, per-source sync health, index queue (pending, failed, oldest pending, recent errors), item counts by kind, database size, embedding progress and last error, AI enrichment state (enabled, model, today's requests and tokens, batches in flight) and the last backup. Overall health SHALL be false when any source is unhealthy or any index job has failed permanently.

#### Scenario: Failed job
- **WHEN** an index job has exhausted its retries
- **THEN** the status report is unhealthy and shows the job's error

### Requirement: Daily verified backups
The system SHALL make a full database backup daily, restore it into a scratch database, compare the row counts of the core tables (raw archive, messages, items, summaries, identities) before and after, record the result, and keep backups for 14 days by default. A backup older than 2 days SHALL be reported as stale.

#### Scenario: Successful backup
- **WHEN** the daily backup runs
- **THEN** the status report shows its time, size and "restored counts match"

#### Scenario: Broken restore
- **WHEN** a restored backup has different row counts than the live database
- **THEN** the backup is recorded as a restore mismatch and shown in the status report

#### Scenario: Backups stopped
- **WHEN** no backup has succeeded for more than 2 days
- **THEN** the status report marks the backup as stale

### Requirement: AI cost is estimated before spending
The system SHALL estimate the AI enrichment cost of the current backlog (conversations not yet summarized with the current model and prompt) without making AI requests.

#### Scenario: Before enabling enrichment
- **WHEN** the owner runs the cost estimate with enrichment disabled
- **THEN** the number of pending conversations and the estimated cost at regular and batch prices are shown
