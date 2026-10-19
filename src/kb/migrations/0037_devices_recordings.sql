-- Recorder apps (calendar-meetings spec; design D22): paired devices and delivered recordings.
CREATE TABLE devices (
    id bigserial PRIMARY KEY,
    name text NOT NULL,
    platform text NOT NULL DEFAULT '',
    token_hash text NOT NULL UNIQUE,          -- sha256 of the device token; the token is never stored
    default_scope text NOT NULL DEFAULT 'personal',
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz,
    revoked_at timestamptz
);

CREATE TABLE device_pair_codes (
    code_hash text PRIMARY KEY,
    expires_at timestamptz NOT NULL,
    used_at timestamptz
);

-- Transcripts and notes of calls and meetings (from a device or attached by hand).
CREATE TABLE recordings (
    id bigserial PRIMARY KEY,
    device_id bigint REFERENCES devices (id) ON DELETE SET NULL,
    event_id bigint REFERENCES events (id) ON DELETE SET NULL,
    kind text NOT NULL CHECK (kind IN ('call', 'meeting', 'voice_note', 'notes')),
    source text NOT NULL DEFAULT '',          -- Zoom, Telegram, in person, upload…
    title text NOT NULL DEFAULT '',
    started_at timestamptz NOT NULL,
    ended_at timestamptz NOT NULL,
    language text,
    segments jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{speaker, is_owner, start, end, text}], redacted
    notes text NOT NULL DEFAULT '',                -- redacted
    idempotency_key text UNIQUE,
    scopes text[] NOT NULL DEFAULT '{unsorted}',
    item_id bigint,
    result jsonb,                                  -- {summary, decisions, actions}
    processed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX recordings_event ON recordings (event_id);
CREATE INDEX recordings_unprocessed ON recordings (created_at) WHERE processed_at IS NULL;
