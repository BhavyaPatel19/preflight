-- The embedder ablation (evals/embedder/RESULTS.md) priced BAAI/bge-large-en-v1.5 at
-- +0.127 Recall@20 over bge-base on the same queries; the corpus moves to 1024-d.
-- 768-d vectors cannot be cast, so the column is rebuilt empty and
-- `preflight corpus reembed` refills it (resumable: it skips rows already carrying the
-- target model). The HNSW index is created afterwards by `preflight corpus reindex` —
-- building it once over the loaded table is far faster than maintaining it through
-- 316k updates, and lets it be built with a higher ef_construction than the default.

DROP INDEX IF EXISTS chunks_embedding_idx;
ALTER TABLE chunks DROP COLUMN IF EXISTS embedding;
ALTER TABLE chunks ADD COLUMN embedding vector(1024);

-- notams.embedding was never populated; keep it in step with the corpus.
DROP INDEX IF EXISTS notams_embedding_idx;
ALTER TABLE notams ALTER COLUMN embedding TYPE vector(1024);
CREATE INDEX notams_embedding_idx ON notams USING hnsw (embedding vector_cosine_ops);
