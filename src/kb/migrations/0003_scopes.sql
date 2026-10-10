-- Scope rules created from the unsorted review, per-item scope overrides, archived scopes.

CREATE TABLE scope_rules (
    id          bigserial PRIMARY KEY,
    kind        text        NOT NULL CHECK (kind IN ('address', 'domain', 'chat', 'folder')),
    value       text        NOT NULL,
    source_id   text,
    scopes      text[]      NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    UNIQUE (kind, value, source_id)
);

CREATE TABLE scope_overrides (
    source_id   text        NOT NULL,
    unit_key    text        NOT NULL,
    scopes      text[]      NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, unit_key)
);

CREATE TABLE archived_scopes (
    scope       text        PRIMARY KEY,
    archived_at timestamptz NOT NULL DEFAULT now()
);
