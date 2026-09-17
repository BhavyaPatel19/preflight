# Retrieval evaluation

Run `74ad409` at 2026-09-17T09:26:11+00:00 · corpus 75,709 documents / 316,226 chunks · embedder `BAAI/bge-large-en-v1.5` · reranker `BAAI/bge-reranker-base` · 40 candidates per channel, RRF k=60

**Synopsis → narrative** (300 ASRS queries; synopsis chunks hidden):

| config | Recall@5 | Recall@10 | Recall@20 | MRR@20 | nDCG@10 | p50 ms | p95 ms |
|---|---:|---:|---:|---:|---:|---:|---:|
| dense | 0.410 | 0.463 | 0.527 | 0.321 | 0.351 | 67 | 192 |
| lexical | 0.363 | 0.403 | 0.483 | 0.264 | 0.294 | 221 | 258 |
| hybrid | 0.443 | 0.507 | 0.560 | 0.361 | 0.393 | 272 | 310 |
| dense+rerank | 0.453 | 0.517 | 0.560 | 0.357 | 0.393 | 738 | 829 |
| hybrid+rerank | 0.457 | 0.530 | 0.597 | 0.373 | 0.407 | 978 | 1226 |

**Rerank lift** (nDCG@10, hybrid+rerank − dense): **+0.056**

**Identifier queries** (50 `runway <NN>` queries with the airport as a metadata filter; relevant = chunk at that airport mentioning that runway):

| config | P@10 |
|---|---:|
| dense | 0.624 |
| lexical | 0.748 |
| hybrid | 0.736 |
| dense+rerank | 0.746 |
| hybrid+rerank | 0.774 |

What this measures: paraphrase-to-passage retrieval and exact-identifier retrieval,
both with objective labels. What it does not: judged precedent relevance for
briefing-style queries — that is the Sprint 5 golden set.
