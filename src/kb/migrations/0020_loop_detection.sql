-- Loop detection runs once per conversation content (content_hash at the last check).
ALTER TABLE items ADD COLUMN loops_checked text;
