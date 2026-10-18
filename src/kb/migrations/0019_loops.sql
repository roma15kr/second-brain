-- Open loops (open-loops spec, design D7): replies owed, promises by/to the owner, manual loops.
CREATE TABLE loops (
    id bigserial PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('needs_reply', 'i_owe', 'owed_to_me', 'manual')),
    title text NOT NULL,
    item_id bigint,
    counterpart text NOT NULL DEFAULT '',
    scopes text[] NOT NULL DEFAULT '{}',
    source_message_key text,
    source_link text,
    status text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'done', 'snoozed', 'dismissed')),
    due_date date,
    snoozed_until date,
    created_at timestamptz NOT NULL DEFAULT now(),
    opened_at timestamptz NOT NULL DEFAULT now(),  -- when the conversation opened it
    closed_at timestamptz,
    closing_message_key text
);
CREATE INDEX loops_status ON loops (status, due_date);
CREATE INDEX loops_item ON loops (item_id);
-- At most one live needs-reply loop per conversation.
CREATE UNIQUE INDEX loops_one_needs_reply ON loops (item_id)
    WHERE kind = 'needs_reply' AND status IN ('open', 'snoozed');

CREATE TABLE loop_events (
    id bigserial PRIMARY KEY,
    loop_id bigint NOT NULL REFERENCES loops (id) ON DELETE CASCADE,
    action text NOT NULL,
    by text NOT NULL CHECK (by IN ('system', 'owner')),
    detail jsonb NOT NULL DEFAULT '{}'::jsonb,
    at timestamptz NOT NULL DEFAULT now()
);

-- Messages whose loop the owner dismissed: detection never recreates a loop from them.
CREATE TABLE loop_dismissed_sources (
    source_message_key text PRIMARY KEY,
    at timestamptz NOT NULL DEFAULT now()
);
