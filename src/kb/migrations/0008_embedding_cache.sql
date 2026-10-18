-- Embeddings keyed by embedded_key (content + summary + model) survive item rebuilds.
CREATE TABLE embedding_cache (
    key        text PRIMARY KEY,
    embedding  vector(1024) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Seed from items already embedded.
INSERT INTO embedding_cache (key, embedding)
SELECT embedded_key, embedding FROM items
WHERE embedding IS NOT NULL AND embedded_key IS NOT NULL
ON CONFLICT DO NOTHING;
