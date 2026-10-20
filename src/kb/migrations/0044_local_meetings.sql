-- Meetings that are not in any connected calendar (mac-recorder-v1 D7b): a built-in calendar
-- "Second brain", and a project per meeting (one local calendar holds several projects).
ALTER TABLE events ADD COLUMN scopes text[];   -- NULL: the calendar's mark

INSERT INTO connector_accounts (kind, label, settings, secret)
SELECT 'calendar', 'Second brain', '{"type": "local"}'::jsonb, NULL
WHERE NOT EXISTS (
    SELECT 1 FROM connector_accounts WHERE kind = 'calendar' AND settings->>'type' = 'local'
);
INSERT INTO calendars (account_id, href, name, sync, scopes, remind_minutes)
SELECT id, 'local', 'Second brain', true, '{unsorted}', 0 FROM connector_accounts
WHERE kind = 'calendar' AND settings->>'type' = 'local'
ON CONFLICT (account_id, href) DO NOTHING;
