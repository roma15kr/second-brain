-- Dictation in the web OS (voice-dictation spec): audio only until it is transcribed.
CREATE TABLE dictations (
    id bigserial PRIMARY KEY,
    status text NOT NULL DEFAULT 'uploaded'
        CHECK (status IN ('uploaded', 'transcribing', 'done', 'failed')),
    audio_path text,                    -- NULL once deleted
    mime text NOT NULL,
    seconds numeric(8, 1) NOT NULL DEFAULT 0,
    transcript text,                    -- redacted
    forms jsonb NOT NULL DEFAULT '{}'::jsonb,
    cost_usd numeric(10, 4) NOT NULL DEFAULT 0,
    attempts int NOT NULL DEFAULT 0,
    error text,
    saved_doc_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    attempted_at timestamptz
);
CREATE INDEX dictations_created ON dictations (created_at DESC);
