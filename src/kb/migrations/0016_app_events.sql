-- Usage events for the success metric (web-dashboard spec: usage events are recorded).
CREATE TABLE app_events (
    id bigserial PRIMARY KEY,
    kind text NOT NULL,
    ref text NOT NULL,
    value jsonb NOT NULL DEFAULT '{}'::jsonb,
    at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX app_events_ref ON app_events (ref, kind);
CREATE INDEX app_events_at ON app_events (at);
