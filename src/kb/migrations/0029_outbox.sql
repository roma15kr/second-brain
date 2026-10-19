-- Email sent on the owner's tap waits here for 10 seconds (undo), then the routines service sends
-- it once (assistant-actions: send on tap; design D17).
CREATE TABLE outbox (
    id bigserial PRIMARY KEY,
    suggestion_id bigint NOT NULL UNIQUE REFERENCES suggestions (id),
    status text NOT NULL DEFAULT 'pending_send'
        CHECK (status IN ('pending_send', 'cancelled', 'sending', 'sent', 'failed')),
    send_after timestamptz NOT NULL,
    message_id text,
    sent_at timestamptz,
    error text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outbox_due ON outbox (send_after) WHERE status = 'pending_send';
