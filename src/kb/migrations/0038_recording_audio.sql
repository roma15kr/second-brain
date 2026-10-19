-- Meeting audio, 12 months (calendar-meetings spec; ADR 0010 amendment; design D22).
CREATE TABLE recording_audio (
    id bigserial PRIMARY KEY,
    recording_id bigint NOT NULL REFERENCES recordings (id) ON DELETE CASCADE,
    track text NOT NULL CHECK (track IN ('owner', 'others', 'mixed')),
    mime text NOT NULL,
    total_bytes bigint NOT NULL CHECK (total_bytes > 0),
    received_bytes bigint NOT NULL DEFAULT 0,
    sha256 text NOT NULL,                      -- announced by the app, verified at the end
    duration_seconds numeric(10, 1),
    path text NOT NULL,                        -- final path (exists once complete)
    complete boolean NOT NULL DEFAULT false,
    recorded_at timestamptz NOT NULL,
    expires_at timestamptz NOT NULL,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (recording_id, track)
);
CREATE INDEX recording_audio_expiry ON recording_audio (expires_at) WHERE deleted_at IS NULL;

ALTER TABLE backup_checks ADD COLUMN kind text NOT NULL DEFAULT 'db';
