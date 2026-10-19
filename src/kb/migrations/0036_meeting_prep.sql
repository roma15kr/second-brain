-- Meeting preparation (calendar-meetings spec): facts + a short agenda, ready before the meeting.
ALTER TABLE events ADD COLUMN prep jsonb;
ALTER TABLE events ADD COLUMN prepared_at timestamptz;
