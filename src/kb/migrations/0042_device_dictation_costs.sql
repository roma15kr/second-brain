-- Dictation from paired devices, and a ledger of transcription costs (dictation and calls) that
-- counts towards the monthly AI budget (mac-recorder-v1).
ALTER TABLE dictations ADD COLUMN device_id bigint REFERENCES devices (id) ON DELETE SET NULL;

CREATE TABLE transcription_costs (
    id bigserial PRIMARY KEY,
    day date NOT NULL,
    kind text NOT NULL CHECK (kind IN ('dictation', 'call')),
    provider text NOT NULL,
    model text NOT NULL,
    seconds numeric(10, 1) NOT NULL,
    usd numeric(10, 5) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX transcription_costs_day ON transcription_costs (day);
