-- Images the owner adds to a ClickUp comment draft; uploaded to the task only when approved.
CREATE TABLE suggestion_files (
    id bigserial PRIMARY KEY,
    suggestion_id bigint NOT NULL REFERENCES suggestions (id) ON DELETE CASCADE,
    filename text NOT NULL,
    mime text NOT NULL,
    data bytea NOT NULL,
    uploaded_url text,                      -- set once ClickUp has it (no second upload on retry)
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX suggestion_files_suggestion ON suggestion_files (suggestion_id);
