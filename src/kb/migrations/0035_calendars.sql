-- Calendars, read-only (calendar-meetings spec; design D15): Google secret iCal addresses and
-- CalDAV (Apple iCloud). Accounts live in connector_accounts (kind 'calendar',
-- settings.type 'ical' or 'caldav'; the iCal address or the app password is the sealed secret).

CREATE TABLE calendars (
    id bigserial PRIMARY KEY,
    account_id bigint NOT NULL REFERENCES connector_accounts (id) ON DELETE CASCADE,
    href text NOT NULL,                 -- CalDAV collection URL, or the iCal address (secret)
    name text NOT NULL,
    sync boolean NOT NULL DEFAULT false,
    scopes text[] NOT NULL DEFAULT '{}',
    remind_minutes int NOT NULL DEFAULT 10 CHECK (remind_minutes BETWEEN 0 AND 240),
    synced_at timestamptz,
    error text,
    UNIQUE (account_id, href)
);

CREATE TABLE events (
    id bigserial PRIMARY KEY,
    calendar_id bigint NOT NULL REFERENCES calendars (id) ON DELETE CASCADE,
    uid text NOT NULL,
    start_at timestamptz NOT NULL,
    end_at timestamptz NOT NULL,
    all_day boolean NOT NULL DEFAULT false,
    title text NOT NULL DEFAULT '',
    location text NOT NULL DEFAULT '',
    link text,                          -- video call link when one is found
    description text NOT NULL DEFAULT '',
    attendees jsonb NOT NULL DEFAULT '[]'::jsonb,   -- [{email, name, status}]
    my_status text,                     -- ACCEPTED / DECLINED / TENTATIVE / NEEDS-ACTION / NULL
    cancelled boolean NOT NULL DEFAULT false,
    reminded_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (calendar_id, uid, start_at)
);
CREATE INDEX events_start ON events (start_at);

ALTER TABLE push_subscriptions ALTER COLUMN routines
    SET DEFAULT '{morning,revision,evening,weekly_review,weekly_plan,clickup,assistant,meetings}';
UPDATE push_subscriptions SET routines = array_append(routines, 'meetings')
    WHERE NOT ('meetings' = ANY (routines));
