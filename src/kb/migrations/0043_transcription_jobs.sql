-- Cloud transcription of uploaded call tracks, run by the routines service (mac-recorder-v1 D4).
CREATE TABLE transcription_jobs (
    id bigserial PRIMARY KEY,
    recording_id bigint NOT NULL REFERENCES recordings (id) ON DELETE CASCADE,
    speakers boolean NOT NULL DEFAULT false,      -- separate the speakers of the "others" track
    status text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
    error text,
    usd numeric(10, 5),
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX transcription_jobs_queued ON transcription_jobs (created_at) WHERE status = 'queued';
