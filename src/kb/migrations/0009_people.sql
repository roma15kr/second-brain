-- People directory: one person, many identities (email, Telegram id/username, phone).
-- Messages and items carry identity keys; merging/splitting people only moves identities.

CREATE TABLE people (
    id           bigserial PRIMARY KEY,
    display_name text        NOT NULL,
    merged_into  bigint REFERENCES people(id),
    created_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE identities (
    id           bigserial PRIMARY KEY,
    person_id    bigint      NOT NULL REFERENCES people(id),
    key          text        NOT NULL UNIQUE,     -- 'email:a@b.c' | 'tg:123' | 'tgu:name' | 'phone:+380…'
    display_name text,
    created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX identities_person ON identities (person_id);

CREATE TABLE person_merges (
    id            bigserial PRIMARY KEY,
    kept_id       bigint      NOT NULL REFERENCES people(id),
    merged_id     bigint      NOT NULL REFERENCES people(id),
    identity_ids  bigint[]    NOT NULL,
    reason        text        NOT NULL,           -- 'manual' | 'auto:<key>'
    created_at    timestamptz NOT NULL DEFAULT now(),
    undone_at     timestamptz
);

ALTER TABLE messages ADD COLUMN identity_keys text[] NOT NULL DEFAULT '{}';
ALTER TABLE items ADD COLUMN identity_keys text[] NOT NULL DEFAULT '{}';
CREATE INDEX items_identity_keys ON items USING gin (identity_keys);
