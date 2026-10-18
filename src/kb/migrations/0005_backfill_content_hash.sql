-- Items built before 0004 have no content_hash, which made them look already summarized.
-- Same formula as kb.distill.content_hash: sha256 of "<title>\n<raw_text>".
UPDATE items
SET content_hash = encode(sha256(convert_to(coalesce(title, '') || E'\n' || raw_text, 'UTF8')), 'hex')
WHERE content_hash IS NULL;
