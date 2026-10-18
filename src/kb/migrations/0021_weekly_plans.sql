-- Monday weekly plan: proposed priorities, accepted (possibly edited) by the owner.
CREATE TABLE weekly_plans (
    brief_id bigint PRIMARY KEY REFERENCES briefs (id) ON DELETE CASCADE,
    week_start date NOT NULL,
    proposed jsonb NOT NULL,
    accepted jsonb,
    accepted_at timestamptz,
    edited boolean NOT NULL DEFAULT false
);
CREATE INDEX weekly_plans_week ON weekly_plans (week_start);
