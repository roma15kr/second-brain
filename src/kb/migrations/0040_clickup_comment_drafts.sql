-- Comments on ClickUp tasks, drafted by the assistant and posted only after approval.
ALTER TABLE suggestions DROP CONSTRAINT suggestions_kind_check;
ALTER TABLE suggestions ADD CONSTRAINT suggestions_kind_check CHECK (kind IN
    ('reply_email', 'email', 'reply_tg', 'nudge', 'task', 'delegate', 'decline',
     'clickup_comment'));
