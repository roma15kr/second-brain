-- Routine runs are retried once after a failure (design D4).
ALTER TABLE routine_runs ADD COLUMN attempts int NOT NULL DEFAULT 1;
