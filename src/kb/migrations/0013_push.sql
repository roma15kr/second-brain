-- Web Push subscriptions, one per device/browser (web-access spec: push per device and routine).
CREATE TABLE push_subscriptions (
    id bigserial PRIMARY KEY,
    endpoint text NOT NULL UNIQUE,
    p256dh text NOT NULL,
    auth text NOT NULL,
    device text NOT NULL DEFAULT '',
    routines text[] NOT NULL
        DEFAULT '{morning,revision,evening,weekly_review,weekly_plan}',
    created_at timestamptz NOT NULL DEFAULT now(),
    last_sent_at timestamptz,
    last_error text
);
