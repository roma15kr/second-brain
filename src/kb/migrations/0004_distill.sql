-- AI enrichment of conversation units: fields on items (searchable), a cache of results keyed by
-- input hash (survives rebuilds), daily usage for cost caps, batch tracking.

ALTER TABLE items
    ADD COLUMN content_hash    text,
    ADD COLUMN question        text,
    ADD COLUMN summary         text,
    ADD COLUMN outcome         text,
    ADD COLUMN entities        jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN language        text,
    ADD COLUMN distilled_key   text,
    ADD COLUMN distilled_at    timestamptz,
    ADD COLUMN distill_batch   text;

DROP INDEX items_tsv;
ALTER TABLE items DROP COLUMN tsv;
ALTER TABLE items ADD COLUMN tsv tsvector GENERATED ALWAYS AS (
    to_tsvector('simple'::regconfig,
        coalesce(title, '') || ' ' || coalesce(question, '') || ' ' || coalesce(summary, '') || ' '
        || coalesce(outcome, '') || ' ' || raw_text)
) STORED;
CREATE INDEX items_tsv ON items USING gin (tsv);
CREATE INDEX items_distill_pending ON items (last_activity_at) WHERE NOT hidden;

CREATE TABLE distillations (
    source_id     text        NOT NULL,
    unit_key      text        NOT NULL,
    distill_key   text        NOT NULL,   -- content hash : model : prompt version
    model         text        NOT NULL,
    result        jsonb       NOT NULL,
    input_tokens  int         NOT NULL DEFAULT 0,
    output_tokens int         NOT NULL DEFAULT 0,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (source_id, unit_key, distill_key)
);

CREATE TABLE llm_usage (
    day           date        NOT NULL,
    source_id     text        NOT NULL,
    model         text        NOT NULL,
    purpose       text        NOT NULL,
    requests      int         NOT NULL DEFAULT 0,
    input_tokens  bigint      NOT NULL DEFAULT 0,
    output_tokens bigint      NOT NULL DEFAULT 0,
    PRIMARY KEY (day, source_id, model, purpose)
);

CREATE TABLE distill_batches (
    id                bigserial PRIMARY KEY,
    provider_batch_id text        NOT NULL UNIQUE,
    model             text        NOT NULL,
    status            text        NOT NULL,
    requests          int         NOT NULL,
    refs              jsonb       NOT NULL,  -- custom_id -> {source_id, unit_key, distill_key}
    created_at        timestamptz NOT NULL DEFAULT now(),
    finished_at       timestamptz
);
