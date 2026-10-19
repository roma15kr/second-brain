-- Requests to the assistant by text or voice, kept in threads (assistant-requests spec).
CREATE TABLE assistant_threads (
    id bigserial PRIMARY KEY,
    title text NOT NULL DEFAULT '',
    pinned boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX assistant_threads_updated ON assistant_threads (updated_at DESC);

CREATE TABLE assistant_requests (
    id bigserial PRIMARY KEY,
    thread_id bigint NOT NULL REFERENCES assistant_threads (id) ON DELETE CASCADE,
    text text NOT NULL,                 -- redacted
    status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
    steps jsonb NOT NULL DEFAULT '[]'::jsonb,
    answer_md text,                     -- redacted
    refs text[] NOT NULL DEFAULT '{}',
    error text,
    cost_usd numeric(10, 4) NOT NULL DEFAULT 0,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE INDEX assistant_requests_thread ON assistant_requests (thread_id, id);
