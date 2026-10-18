-- Meaning-based search: one embedding per conversation unit (pgvector, cosine, HNSW).
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE items
    ADD COLUMN embedding     vector(1024),
    ADD COLUMN embedded_key  text;
CREATE INDEX items_embedding ON items USING hnsw (embedding vector_cosine_ops);
