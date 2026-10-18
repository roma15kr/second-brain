-- Re-read ClickUp tasks once with all comments and threaded replies (earlier syncs stored only
-- the 25 newest comments): reset list cursors and forget stored update times.
UPDATE clickup_lists SET cursor_ms = 0;
UPDATE items SET metadata = metadata - 'date_updated' WHERE kind = 'clickup_task';
