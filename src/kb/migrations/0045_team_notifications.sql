-- assistant-moderation-v1: ClickUp events about a member of the owner's team name that member.
ALTER TABLE clickup_notifications ADD COLUMN IF NOT EXISTS subject text;
ALTER TABLE clickup_notifications DROP CONSTRAINT clickup_notifications_kind_check;
ALTER TABLE clickup_notifications ADD CONSTRAINT clickup_notifications_kind_check CHECK (kind IN
    ('assigned', 'group_assigned', 'mentioned', 'group_mentioned', 'comment_assigned',
     'followed_new_task', 'followed_comment', 'followed_chat', 'chat_direct',
     'team_assigned', 'team_mentioned'));
