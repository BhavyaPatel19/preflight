-- Dev-default embedder is BAAI/bge-base-en-v1.5 (768-d). Record which model
-- produced each vector so a model swap is a re-embed, not a mystery.
-- See docs/adr/0003.

ALTER TABLE chunks
    ALTER COLUMN embedding TYPE vector(768),
    ADD COLUMN IF NOT EXISTS embedding_model TEXT,
    ADD COLUMN IF NOT EXISTS chars INTEGER;

ALTER TABLE notams
    ALTER COLUMN embedding TYPE vector(768),
    ADD COLUMN IF NOT EXISTS embedding_model TEXT;

DROP INDEX IF EXISTS chunks_embedding_idx;
DROP INDEX IF EXISTS notams_embedding_idx;
CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX notams_embedding_idx ON notams USING hnsw (embedding vector_cosine_ops);

CREATE INDEX IF NOT EXISTS chunks_document_idx ON chunks (document_id, ordinal);
