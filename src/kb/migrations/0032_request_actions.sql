-- Drafts and tasks prepared from a request wait in the same approval queue (assistant-requests).
ALTER TABLE suggestions DROP CONSTRAINT suggestions_kind_check;
ALTER TABLE suggestions ADD CONSTRAINT suggestions_kind_check CHECK (kind IN
    ('reply_email', 'email', 'reply_tg', 'nudge', 'task', 'delegate', 'decline'));
ALTER TABLE suggestions ADD COLUMN origin text NOT NULL DEFAULT 'routine'
    CHECK (origin IN ('routine', 'command'));
ALTER TABLE suggestions ADD COLUMN request_id bigint REFERENCES assistant_requests (id)
    ON DELETE SET NULL;
-- what a request created or changed (suggestions, loop changes with their undo) and its last search
ALTER TABLE assistant_requests ADD COLUMN created jsonb NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE assistant_requests ADD COLUMN search jsonb;
