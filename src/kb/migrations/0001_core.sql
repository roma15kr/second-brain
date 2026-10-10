-- Core tables: lossless archive, single retrieval table, job queue, sync cursors.

CREATE TABLE raw_records (
    id            bigserial PRIMARY KEY,
    source_id     text        NOT NULL,
    external_id   text        NOT NULL,
    kind          text        NOT NULL,
    occurred_at   timestamptz,
    payload       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    blob          bytea,
    content_hash  text        NOT NULL,
    fetched_at    timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, external_id, content_hash)
);
CREATE INDEX raw_records_source_external ON raw_records (source_id, external_id);

CREATE TABLE items (
    id               bigserial PRIMARY KEY,
    source_id        text        NOT NULL,
    source_item_key  text        NOT NULL,
    kind             text        NOT NULL,
    scopes           text[]      NOT NULL DEFAULT '{unsorted}',
    title            text,
    raw_text         text        NOT NULL DEFAULT '',
    participants     text[]      NOT NULL DEFAULT '{}',
    occurred_at      timestamptz,
    last_activity_at timestamptz,
    locator          text,
    metadata         jsonb       NOT NULL DEFAULT '{}'::jsonb,
    hidden           boolean     NOT NULL DEFAULT false,
    updated_at       timestamptz NOT NULL DEFAULT now(),
    tsv              tsvector GENERATED ALWAYS AS (
        to_tsvector('simple'::regconfig, coalesce(title, '') || ' ' || raw_text)
    ) STORED,
    UNIQUE (source_id, source_item_key)
);
CREATE INDEX items_tsv ON items USING gin (tsv);
CREATE INDEX items_scopes ON items USING gin (scopes);
CREATE INDEX items_last_activity ON items (last_activity_at DESC);

CREATE TABLE jobs (
    id          bigserial PRIMARY KEY,
    kind        text        NOT NULL,
    payload     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    run_after   timestamptz NOT NULL DEFAULT now(),
    attempts    int         NOT NULL DEFAULT 0,
    last_error  text,
    locked_at   timestamptz,
    done_at     timestamptz,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX jobs_pending ON jobs (run_after) WHERE done_at IS NULL;

CREATE TABLE sync_state (
    source_id   text        NOT NULL,
    key         text        NOT NULL,
    value       jsonb       NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, key)
);
