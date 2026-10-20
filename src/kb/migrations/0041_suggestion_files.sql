-- Images for ClickUp comment drafts (unused since 2026-10-20: the owner adds images in ClickUp
-- itself via "Copy & open in ClickUp"); kept because migrations are never rewritten.
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
