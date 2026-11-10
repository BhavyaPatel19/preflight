# Embedder ablation

Run `f0bb228` at 2026-11-10T04:46:07+00:00 · 300 synopsis queries · 40,000 narrative chunks (300 target reports, the rest random) · exact cosine search in memory, no reranker

| model | dim | Recall@5 | Recall@10 | Recall@20 | nDCG@10 | Δ R@20 vs first | chunks/s |
|---|---:|---:|---:|---:|---:|---:|---:|
| `BAAI/bge-large-en-v1.5` | 1024 | 0.543 | 0.613 | 0.693 | 0.473 | +0.000 | 20.1 |
| `models/bge-large-asrs` | 1024 | 0.760 | 0.837 | 0.893 | 0.692 | +0.200 | 22.5 |

Numbers here are higher than `evals/retrieval/RESULTS.md` by construction — a 40,000-chunk subset and exact search instead of 316k chunks through HNSW — and are not comparable to it. Only the gap between rows is the finding. A model that wins here earns a full re-embed and the real eval.

**What transferred (run 7, `evals/retrieval/HISTORY.md`):** the ranking gains did — full-corpus dense nDCG@10 +0.04, Recall@5 +0.08 — and the Recall@20 gain did not (+0.01 dense, flat after reranking). With 16× fewer distractors than the corpus, a subset measures how well a model orders near neighbours, not how often the target is anywhere in the top 20 of 316k chunks. Read the Recall@20 column here as an upper bound, and the nDCG column as the number to believe.
