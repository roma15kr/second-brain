-- Reports from requests, the over-budget path and the "answer ready" push (assistant-requests).
ALTER TABLE assistant_requests ADD COLUMN report jsonb;
ALTER TABLE assistant_requests ADD COLUMN allow_over_budget boolean NOT NULL DEFAULT false;
ALTER TABLE assistant_requests ADD COLUMN needs_budget boolean NOT NULL DEFAULT false;
ALTER TABLE assistant_requests ADD COLUMN saved_doc_id bigint;
ALTER TABLE push_subscriptions ALTER COLUMN routines
    SET DEFAULT '{morning,revision,evening,weekly_review,weekly_plan,clickup,assistant}';
UPDATE push_subscriptions SET routines = array_append(routines, 'assistant')
    WHERE NOT ('assistant' = ANY (routines));
