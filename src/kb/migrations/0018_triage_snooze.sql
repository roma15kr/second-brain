-- Inbox actions on triaged mail: snooze until a time.
ALTER TABLE triage ADD COLUMN snoozed_until timestamptz;
