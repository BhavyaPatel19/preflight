# Embedder ablation

Run `97f532f` at 2026-09-14T19:07:15+00:00 · 300 synopsis queries · 20,000 narrative chunks (300 target reports, the rest random) · exact cosine search in memory, no reranker

| model | dim | Recall@5 | Recall@10 | Recall@20 | nDCG@10 | Δ R@20 vs first | chunks/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| `BAAI/bge-base-en-v1.5` | 768 | 0.507 | 0.583 | 0.640 | 0.447 | +0.000 | 64.6 |
| `BAAI/bge-large-en-v1.5` | 1024 | 0.613 | 0.683 | 0.767 | 0.545 | +0.127 | 18.1 |
| `BAAI/bge-m3` | 1024 | 0.557 | 0.610 | 0.670 | 0.505 | +0.030 | 13.5 |

Numbers here are higher than `evals/retrieval/RESULTS.md` by construction — a 20,000-chunk subset and exact search instead of 316k chunks through HNSW — and are not comparable to it. Only the gap between rows is the finding. A model that wins here earns a full re-embed and the real eval.
