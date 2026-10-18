-- Web OS (web-os-v1): owner sign-in with passkeys, sessions, settings, routine runs and briefs.

CREATE TABLE webauthn_credentials (
    id bytea PRIMARY KEY,
    public_key bytea NOT NULL,
    sign_count bigint NOT NULL DEFAULT 0,
    transports text[] NOT NULL DEFAULT '{}',
    device text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    last_used_at timestamptz
);

-- One pending WebAuthn ceremony per browser (id is kept in a short-lived HttpOnly cookie).
CREATE TABLE webauthn_challenges (
    id text PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('register', 'login')),
    challenge bytea NOT NULL,
    setup_code_hash bytea,
    expires_at timestamptz NOT NULL
);

-- First-passkey enrollment codes created on the server (`kb web setup-code`); stored hashed.
CREATE TABLE setup_codes (
    code_hash bytea PRIMARY KEY,
    created_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    used_at timestamptz
);

CREATE TABLE recovery_codes (
    id bigserial PRIMARY KEY,
    code_hash bytea NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    used_at timestamptz
);

-- Session tokens are random; only their sha256 is stored.
CREATE TABLE web_sessions (
    token_hash bytea PRIMARY KEY,
    device text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    last_seen_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL,
    needs_passkey boolean NOT NULL DEFAULT false
);

CREATE TABLE app_settings (
    key text PRIMARY KEY,
    value jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE briefs (
    id bigserial PRIMARY KEY,
    routine text NOT NULL,
    window_start timestamptz NOT NULL,
    window_end timestamptz NOT NULL,
    headline text NOT NULL,
    sections jsonb NOT NULL,
    mode text NOT NULL CHECK (mode IN ('ai', 'data')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX briefs_routine_created ON briefs (routine, created_at DESC);

-- One row per (routine, scheduled slot): the unique key makes runs idempotent.
CREATE TABLE routine_runs (
    id bigserial PRIMARY KEY,
    routine text NOT NULL,
    slot timestamptz NOT NULL,
    status text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'done', 'failed')),
    delayed boolean NOT NULL DEFAULT false,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    error text,
    brief_id bigint REFERENCES briefs (id),
    UNIQUE (routine, slot)
);
