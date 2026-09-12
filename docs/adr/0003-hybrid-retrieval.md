# ADR 0003 — Hybrid retrieval in Postgres, reranked; dev-speed models by default

**Status:** accepted · **Date:** 2026-09-12

## Context

The precedent corpus (ASRS narratives, NTSB findings, FAR/AIM) is queried in two very different
registers. One is exact: `28R`, `KSFO`, `ILS 22L` — identifiers that embeddings blur and lexical
search nails. The other is narrative: "lined up with the taxiway at night" — which lexical search
misses when the words differ and embeddings catch. Either channel alone loses one register.

Model weight is a separate question. The spec named `bge-m3` and `bge-reranker-v2-m3` (568M
parameters each, ~2.2 GB each). On a laptop those turn a test run into a coffee break.

## Decision

1. **Dense and lexical candidate sets, fused with reciprocal rank fusion, in one SQL statement.**
   Both channels apply the same metadata filter (`icao`, `source`) *before* ranking, so a filtered
   search is not "rank everything, then drop most of it". RRF (`k = 60`) is rank-based, so the two
   channels' incomparable scores never need calibrating. Channel weights of 0 switch a channel off;
   that is the ablation switch the retrieval eval uses for dense-only / lexical-only / hybrid.

2. **A cross-encoder reranks the fused top-N** (default 40 → top-k). On the first synthetic smoke
   test, the three best fused candidates scored 0.0328 / 0.0320 / 0.0320 — indistinguishable — and
   the reranker separated the right one at 0.62 from the others at 0.08 and 0.02. The rerank lift
   is a number the eval will report, not an assumption.

3. **Lexical is Postgres `tsvector` + `ts_rank`; AND for short queries, OR for long.** Not true
   BM25 (no document-length normalisation). This keeps the stock `pgvector/pgvector` image. If the
   retrieval golden set shows the lexical channel underperforming, ParadeDB's `pg_search` (real
   BM25) is a drop-in at the cost of a different image.

   *Amended 2026-09-12 by the retrieval eval* (`evals/retrieval/HISTORY.md`): the original choice
   was `ts_rank_cd` with OR-joined terms for every query. On 34-term paraphrase queries it matched
   ~81k chunks and took 2 s to rank them, and ranked them badly enough (nDCG@10 0.105) that fusing
   the channel *hurt* hybrid. `ts_rank` is 8× faster and nearly 3× better on the same queries. On
   ≤ 4-term identifier queries, OR let the common word swamp the discriminating one; AND took
   lexical P@10 from 0.13 to 0.75. Neither threshold was chosen by taste.

4. **Dev-default models are the fast pair:** `BAAI/bge-base-en-v1.5` (110M, 768-d) and
   `BAAI/bge-reranker-base` (278M). Both run on Apple Silicon via MPS at ~115 docs/s and
   ~4 pairs/s. The `bge-m3` pair is the upgrade path — multilingual, 8k context — and is
   adopted only if the golden set shows a lift worth the 5× weight. Every chunk records the
   `embedding_model` that produced its vector, so a swap is a re-embed, not a mystery.

5. **Models sit behind two-method protocols** (`Embedder.encode`, `Reranker.score`) and import
   torch lazily. The test suite runs on hash-based fakes with no ML dependency; `pytest -m ml`
   exercises the real models. CI never downloads a model.

## Consequences

- The corpus schema moves to `vector(768)` (migration 004). Going to 1024-d later is a migration
  plus a re-embed, both mechanical.
- Retrieval is fully ablatable from one call site: `mode=` and `rerank=` on `Retriever.search`.
  The Sprint 3 eval reports Recall@k / nDCG@10 per mode and the delta the reranker adds.
- ~1.5 GB of model weights land in the HF cache on first use. Documented; not committed.

## Revisit when

- The retrieval golden set exists and shows lexical recall on identifiers below target → `pg_search`.
- nDCG@10 with `bge-m3` beats `bge-base` by more than the noise floor → swap the default.
- Corpus passes ~1M chunks → revisit HNSW parameters (`m`, `ef_construction`) and ADR 0001.
