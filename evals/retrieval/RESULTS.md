# Retrieval evaluation

Run `4d1c6fe` at 2026-09-14T05:47:25+00:00 · corpus 75,709 documents / 316,226 chunks · embedder `BAAI/bge-base-en-v1.5` · reranker `BAAI/bge-reranker-base` · 40 candidates per channel, RRF k=60

**Synopsis → narrative** (300 ASRS queries; synopsis chunks hidden):

| config | Recall@5 | Recall@10 | Recall@20 | MRR@20 | nDCG@10 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.330 | 0.440 | 0.517 | 0.276 | 0.310 | 46 | 131 |
| lexical | 0.363 | 0.407 | 0.483 | 0.264 | 0.294 | 217 | 249 |
| hybrid | 0.437 | 0.480 | 0.553 | 0.344 | 0.373 | 266 | 304 |
| dense+rerank | 0.427 | 0.500 | 0.547 | 0.340 | 0.376 | 859 | 1001 |
| hybrid+rerank | 0.450 | 0.527 | 0.607 | 0.368 | 0.402 | 1100 | 1395 |

**Rerank lift** (nDCG@10, hybrid+rerank − dense): **+0.091**

**Identifier queries** (50 `runway <NN>` queries with the airport as a metadata filter; relevant = chunk at that airport mentioning that runway):

| config | P@10 |
|---|---:|
| dense | 0.542 |
| lexical | 0.746 |
| hybrid | 0.730 |
| dense+rerank | 0.746 |
| hybrid+rerank | 0.774 |

What this measures: paraphrase-to-passage retrieval and exact-identifier retrieval,
both with objective labels. What it does not: judged precedent relevance for
briefing-style queries — that is the Sprint 5 golden set.
