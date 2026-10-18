-- Goals proposed from core documents and confirmed by the owner (personal-base spec).
CREATE TABLE goals (
    id bigserial PRIMARY KEY,
    document_id bigint REFERENCES documents (id) ON DELETE SET NULL,
    version_id bigint,
    title text NOT NULL,
    scope text NOT NULL,
    measure text NOT NULL DEFAULT '',
    deadline date,
    source_excerpt text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'proposed' CHECK (status IN ('proposed', 'confirmed', 'removed')),
    created_at timestamptz NOT NULL DEFAULT now(),
    confirmed_at timestamptz
);
CREATE INDEX goals_status ON goals (status);
ALTER TABLE documents ADD COLUMN goals_version_id bigint;  -- version goals were proposed from
