# Retrieval evaluation

Run `26c514d` at 2026-09-12T19:11:54+00:00 · corpus 75,709 documents / 316,226 chunks · embedder `BAAI/bge-base-en-v1.5` · reranker `BAAI/bge-reranker-base` · 40 candidates per channel, RRF k=60

**Synopsis → narrative** (300 ASRS queries; synopsis chunks hidden):

| config | Recall@5 | Recall@10 | Recall@20 | MRR@20 | nDCG@10 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.337 | 0.443 | 0.523 | 0.281 | 0.315 | 472 | 522 |
| lexical | 0.363 | 0.403 | 0.483 | 0.264 | 0.294 | 424 | 477 |
| hybrid | 0.430 | 0.487 | 0.553 | 0.350 | 0.379 | 631 | 699 |
| dense+rerank | 0.440 | 0.510 | 0.560 | 0.344 | 0.381 | 1236 | 1378 |
| hybrid+rerank | 0.450 | 0.533 | 0.607 | 0.370 | 0.405 | 1405 | 1686 |

**Rerank lift** (nDCG@10, hybrid+rerank − dense): **+0.091**

**Identifier queries** (50 `runway <NN>` queries with the airport as a metadata filter; relevant = chunk at that airport mentioning that runway):

| config | P@10 |
|---|---:|
| dense | 0.542 |
| lexical | 0.746 |
| hybrid | 0.734 |
| dense+rerank | 0.746 |
| hybrid+rerank | 0.772 |

What this measures: paraphrase-to-passage retrieval and exact-identifier retrieval,
both with objective labels. What it does not: judged precedent relevance for
briefing-style queries — that is the Sprint 5 golden set.
