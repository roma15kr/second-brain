-- ClickUp items for the owner, pushed right away (clickup-integration spec).
CREATE TABLE clickup_notifications (
    key text PRIMARY KEY,             -- 'comment:<id>:<why>' / 'task:<id>:<why>': once per event
    account_id bigint NOT NULL,
    item_id bigint,
    kind text NOT NULL CHECK (kind IN ('assigned', 'group_assigned', 'mentioned',
                                       'group_mentioned', 'comment_assigned',
                                       'followed_new_task', 'followed_comment', 'followed_chat')),
    actor text NOT NULL DEFAULT '',
    event_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    handled_at timestamptz,           -- push sent, or held for the brief (quiet hours)
    pushed boolean NOT NULL DEFAULT false
);
CREATE INDEX clickup_notifications_pending ON clickup_notifications (created_at)
    WHERE handled_at IS NULL;

-- Devices get ClickUp pushes too (switchable per device in Settings).
ALTER TABLE push_subscriptions ALTER COLUMN routines
    SET DEFAULT '{morning,revision,evening,weekly_review,weekly_plan,clickup}';
UPDATE push_subscriptions SET routines = array_append(routines, 'clickup')
    WHERE NOT ('clickup' = ANY (routines));
