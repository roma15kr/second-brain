-- ClickUp (clickup-integration spec, design D14) and the approval queue (design D17).
CREATE TABLE clickup_lists (
    list_id text PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES connector_accounts (id) ON DELETE CASCADE,
    space_id text NOT NULL,
    space_name text NOT NULL DEFAULT '',
    folder_name text NOT NULL DEFAULT '',
    list_name text NOT NULL DEFAULT '',
    sync boolean NOT NULL DEFAULT false,
    scopes text[] NOT NULL DEFAULT '{}',
    default_for_drafts boolean NOT NULL DEFAULT false,
    cursor_ms bigint NOT NULL DEFAULT 0,       -- date_updated of the newest task seen
    seen_at timestamptz NOT NULL DEFAULT now()
);

-- Everything the assistant proposes waits here until the owner approves it.
CREATE TABLE suggestions (
    id bigserial PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('reply_email', 'reply_tg', 'nudge', 'task', 'delegate', 'decline')),
    scopes text[] NOT NULL DEFAULT '{}',
    payload jsonb NOT NULL,
    refs text[] NOT NULL DEFAULT '{}',
    reason text NOT NULL DEFAULT '',
    goal_id bigint,
    item_id bigint,
    status text NOT NULL DEFAULT 'proposed'
        CHECK (status IN ('proposed', 'approved', 'applying', 'applied', 'discarded', 'failed')),
    edited boolean NOT NULL DEFAULT false,
    applied_ref text,
    error text,
    discard_reason text,
    created_at timestamptz NOT NULL DEFAULT now(),
    decided_at timestamptz,
    attempt_started_at timestamptz
);
CREATE INDEX suggestions_status ON suggestions (status, created_at DESC);

ALTER TABLE loops ADD COLUMN clickup_task_id text;
CREATE INDEX loops_clickup_task ON loops (clickup_task_id) WHERE clickup_task_id IS NOT NULL;
