# Embedder ablation

Run `97f532f` at 2026-09-14T19:07:15+00:00 · 300 synopsis queries · 20,000 narrative chunks (300 target reports, the rest random) · exact cosine search in memory, no reranker

| model | dim | Recall@5 | Recall@10 | Recall@20 | nDCG@10 | Δ R@20 vs first | chunks/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| `BAAI/bge-base-en-v1.5` | 768 | 0.507 | 0.583 | 0.640 | 0.447 | +0.000 | 64.6 |
| `BAAI/bge-large-en-v1.5` | 1024 | 0.613 | 0.683 | 0.767 | 0.545 | +0.127 | 18.1 |
| `BAAI/bge-m3` | 1024 | 0.557 | 0.610 | 0.670 | 0.505 | +0.030 | 13.5 |

Numbers here are higher than `evals/retrieval/RESULTS.md` by construction — a 20,000-chunk subset and exact search instead of 316k chunks through HNSW — and are not comparable to it. Only the gap between rows is the finding. A model that wins here earns a full re-embed and the real eval.

**What transferred (run 7, `evals/retrieval/HISTORY.md`):** the ranking gains did — full-corpus dense nDCG@10 +0.04, Recall@5 +0.08 — and the Recall@20 gain did not (+0.01 dense, flat after reranking). With 16× fewer distractors than the corpus, a subset measures how well a model orders near neighbours, not how often the target is anywhere in the top 20 of 316k chunks. Read the Recall@20 column here as an upper bound, and the nDCG column as the number to believe.
