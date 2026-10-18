-- Mail revision passes (design D6): per-pass triage of email threads, sender preferences, and
-- whether a brief should be pushed (quiet passes are stored but not pushed).
CREATE TABLE sender_prefs (
    address text PRIMARY KEY,
    pref text NOT NULL CHECK (pref IN ('noise', 'important')),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE triage (
    id bigserial PRIMARY KEY,
    brief_id bigint NOT NULL REFERENCES briefs (id) ON DELETE CASCADE,
    item_id bigint NOT NULL,
    class text NOT NULL CHECK (class IN ('needs_reply', 'important', 'fyi', 'noise')),
    action text NOT NULL DEFAULT '',
    reason text NOT NULL DEFAULT '',
    sender text,
    done_at timestamptz,
    UNIQUE (brief_id, item_id)
);
CREATE INDEX triage_item ON triage (item_id);

ALTER TABLE briefs ADD COLUMN push boolean NOT NULL DEFAULT true;
