-- Connectors in the web OS (design D11, D13): projects the owner can add, and connected accounts
-- with encrypted credentials.
CREATE TABLE projects (
    name text PRIMARY KEY CHECK (name ~ '^[a-z][a-z0-9_-]{1,30}$'),
    label text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO projects (name, label) VALUES
    ('personal', 'Personal'), ('digisoft', 'Digisoft'), ('quokka', 'Quokka'), ('rdim', 'RDIM');

CREATE TABLE connector_accounts (
    id bigserial PRIMARY KEY,
    kind text NOT NULL CHECK (kind IN ('imap', 'telegram', 'clickup', 'calendar')),
    label text NOT NULL,
    settings jsonb NOT NULL DEFAULT '{}'::jsonb,  -- never secrets
    secret bytea,                                  -- AES-GCM sealed JSON (KB_SECRET_KEY)
    default_scopes text[] NOT NULL DEFAULT '{unsorted}',
    state text NOT NULL DEFAULT 'active' CHECK (state IN ('active', 'disconnected')),
    created_at timestamptz NOT NULL DEFAULT now(),
    checked_at timestamptz
);
