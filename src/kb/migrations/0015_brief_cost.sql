-- AI cost of each brief (assistant-routines spec: record AI cost per run).
ALTER TABLE briefs ADD COLUMN cost_usd numeric(10, 4) NOT NULL DEFAULT 0;
