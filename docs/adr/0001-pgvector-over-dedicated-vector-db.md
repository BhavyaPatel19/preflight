# ADR 0001 — pgvector in Postgres, not a dedicated vector database

**Status:** accepted · **Date:** 2026-09-11

## Context

Every retrieval query in Preflight is a *filtered* similarity search. "Find precedent for this
hazard" is never asked in isolation — it is asked about a specific airport, a phase of flight, and a
window in time, against records that were in force at that instant. The filter is not an
optimisation; it is the question.

The candidates were Postgres with `pgvector`, or a managed vector service (Pinecone, Qdrant Cloud,
Weaviate) alongside Postgres for everything else.

## Decision

One Postgres 16 instance holds vectors (`pgvector`, HNSW, cosine), lexical indexes (`tsvector`,
GIN), and all operational metadata. Hybrid retrieval is one SQL statement: a dense candidate set
and a BM25 candidate set, each pre-filtered on `icao` and time window, fused with reciprocal rank
fusion, then reranked by a cross-encoder in the application.

## Consequences

**Gained**
- Metadata filters are transactional and exact. A NOTAM that expired at 0700Z is excluded at
  0701Z with no eventual-consistency window between two stores.
- The time-travel evaluation is trivial: replaying a case at `snapshot_at` is a `WHERE` clause,
  not a snapshot/restore of a second system.
- One backup, one migration path, one connection pool, one thing to explain.

**Given up**
- Horizontal scaling of the vector index. HNSW in Postgres is comfortable to the low millions of
  vectors; the ASRS corpus is ~200k narratives → ~1M chunks, which fits with room to spare.
- Managed ops. Acceptable for a system with one writer and a handful of readers.

**Revisit when**
- Chunk count passes ~5M, or p95 retrieval latency exceeds 150 ms after index tuning.
- Multi-tenant isolation becomes a requirement.

The retrieval interface is behind a single `Retriever` protocol so this can be swapped without
touching the agents. That is the mitigation, not a plan to swap.
