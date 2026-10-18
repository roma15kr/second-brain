-- One row per message (email or Telegram), redacted. Search items become conversation units
-- (email threads, Telegram conversations) rebuilt from these rows.

CREATE TABLE messages (
    id           bigserial PRIMARY KEY,
    source_id    text        NOT NULL,
    message_key  text        NOT NULL,
    kind         text        NOT NULL,              -- 'email' | 'tg'
    unit_key     text        NOT NULL,
    scopes       text[]      NOT NULL DEFAULT '{unsorted}',
    chat_id      bigint,
    msg_id       bigint,
    topic_id     bigint,
    reply_to     text,
    refs         text[]      NOT NULL DEFAULT '{}',
    subject      text,
    subject_norm text,
    author       text,
    participants text[]      NOT NULL DEFAULT '{}',
    sent_at      timestamptz NOT NULL,
    body         text        NOT NULL DEFAULT '',
    version      text        NOT NULL DEFAULT '',
    hidden       boolean     NOT NULL DEFAULT false,
    locator      text,
    metadata     jsonb       NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (source_id, message_key)
);
CREATE INDEX messages_unit ON messages (source_id, unit_key, sent_at);
CREATE INDEX messages_chat_time ON messages (source_id, chat_id, topic_id, sent_at DESC);
CREATE INDEX messages_refs ON messages USING gin (refs);
CREATE INDEX messages_subject ON messages (source_id, subject_norm, sent_at);

-- Per-message items from slices 1-3 are replaced by units; the indexer re-indexes the archive.
DELETE FROM items WHERE kind IN ('email', 'tg_message');
