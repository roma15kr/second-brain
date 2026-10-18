-- Personal base (personal-base spec, design D16): documents and notes with versions.
CREATE TABLE documents (
    id bigserial PRIMARY KEY,
    title text NOT NULL,
    kind text NOT NULL CHECK (kind IN ('constitution', 'plan', 'goals', 'note', 'reference')),
    scopes text[] NOT NULL CHECK (cardinality(scopes) > 0),
    ai_allowed boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE document_versions (
    id bigserial PRIMARY KEY,
    document_id bigint NOT NULL REFERENCES documents (id) ON DELETE CASCADE,
    filename text NOT NULL,
    size integer NOT NULL,
    sha256 text NOT NULL,
    data bytea NOT NULL,
    text text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX document_versions_doc ON document_versions (document_id, id DESC);
