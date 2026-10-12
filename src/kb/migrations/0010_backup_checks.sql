-- Written by the backup service after each dump + restore test.
CREATE TABLE backup_checks (
    id         bigserial PRIMARY KEY,
    status     text        NOT NULL,   -- ok | restore_mismatch | dump_failed
    dump_file  text,
    detail     text,
    created_at timestamptz NOT NULL DEFAULT now()
);
