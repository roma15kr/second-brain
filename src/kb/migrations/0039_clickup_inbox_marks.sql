-- ClickUp: direct chat messages notify right away; the workspace gets its own mark.
ALTER TABLE clickup_notifications DROP CONSTRAINT clickup_notifications_kind_check;
ALTER TABLE clickup_notifications ADD CONSTRAINT clickup_notifications_kind_check CHECK (kind IN
    ('assigned', 'group_assigned', 'mentioned', 'group_mentioned', 'comment_assigned',
     'followed_new_task', 'followed_comment', 'followed_chat', 'chat_direct'));

-- Owner decision (2026-10-18/19): the Adducate workspace is Quokka only ("is quokka only, not
-- digisoft also"). Its lists had been marked digisoft: mark the workspace quokka and move its
-- digisoft-only lists, tasks, comment chunks and chat days to quokka. No-op elsewhere.
UPDATE connector_accounts SET settings = settings || '{"default_scope": "quokka"}'::jsonb
    WHERE kind = 'clickup' AND label = 'Adducate' AND NOT settings ? 'default_scope';
UPDATE clickup_lists l SET scopes = '{quokka}' FROM connector_accounts a
    WHERE a.id = l.account_id AND a.kind = 'clickup' AND a.label = 'Adducate'
      AND l.scopes = '{digisoft}';
UPDATE items i SET scopes = '{quokka}' FROM connector_accounts a
    WHERE a.kind = 'clickup' AND a.label = 'Adducate' AND i.source_id = 'clickup-' || a.id
      AND i.scopes = '{digisoft}';
