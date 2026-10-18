-- Telegram dialogs chosen in the web OS (source-ingestion spec, design D12) and QR login requests.
CREATE TABLE tg_dialogs (
    chat_id bigint PRIMARY KEY,
    source_id text NOT NULL,
    title text NOT NULL DEFAULT '',
    username text,
    peer_type text NOT NULL DEFAULT 'user',
    last_message_at timestamptz,
    included boolean,            -- NULL: new, to mark; true: ingested; false: ignored
    scopes text[] NOT NULL DEFAULT '{}',
    seen_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE telegram_login (
    id bigserial PRIMARY KEY,
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'qr', 'password_needed', 'done', 'expired', 'failed')),
    qr_url text,
    error text,
    secret bytea,                -- sealed 2FA password, wiped after use
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
