# Retrieval evaluation — run history

One line per run that changed something. `RESULTS.md` is always the latest full run; the JSON
for every run is under `runs/` (gitignored — the numbers that matter are here).

| # | date (UTC) | code | database | change under test | dense nDCG@10 | lexical nDCG@10 | hybrid nDCG@10 | hybrid+rerank nDCG@10 | identifier P@10 (lexical / hybrid+rerank) | lexical p50 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | 2026-09-12 17:57 | `c45044f` | pg16 in Colima | **baseline** — `ts_rank_cd`, OR-joined terms, identifier queries with the ICAO as query text | 0.315 | 0.105 | 0.266 | 0.390 | 0.016 / 0.080 | 856 ms |
| 2 | 2026-09-12 18:42 | step 11 | pg17 native | `ts_rank` instead of `ts_rank_cd`; identifier queries use the airport as a metadata filter; `dense+rerank` added | 0.315 | **0.294** | **0.379** | **0.405** | 0.134 / 0.100 | 421 ms |
| 3 | 2026-09-12 18:48 | step 11 | pg17 native | AND-semantics for ≤ 4-term queries; strict airport filter for identifier queries | — | — | — | — | **0.746 / 0.774** | — |
| 4 | 2026-09-12 19:11 | step 11 | pg17 native | **final full run** at the step-11 retrieval code (recorded sha is the step-12 checkout; retrieval code identical) — `RESULTS.md` | 0.315 | 0.294 | 0.379 | **0.405** | 0.746 / 0.772 | 424 ms |
| 5 | 2026-09-12 20:08 | main | pg17 native | experiment: **100 candidates** per channel instead of 40 (`--candidates 100`) — not adopted | 0.315 | 0.294 | 0.388 | 0.391 | 0.748 / 0.776 | 429 ms |
| 6 | 2026-09-14 05:47 | step 22 | pg17 native | **index-driven SQL**: per-channel filters instead of a materialised `pool` CTE; dense channel is now an HNSW scan (`ef_search=1000`, iterative) instead of an exact sort — `RESULTS.md` | 0.310 | 0.294 | 0.373 | **0.402** | 0.746 / 0.774 | 217 ms |

## What each run taught

**Run 1 → 2: the ranking function was the problem, not the channel.** `ts_rank_cd`
(cover density) on a 34-term OR query matched ~81k chunks and took 2 s to rank them — and ranked
them badly: lexical nDCG@10 was 0.105, and fusing that into hybrid *hurt* (0.266 < dense 0.315).
Switching to `ts_rank` cut latency 8× in a same-engine micro-benchmark and nearly tripled lexical
quality; hybrid now beats dense, and hybrid+rerank beats dense+rerank (0.405 vs 0.381), so the
lexical channel earns its place on paraphrase queries too.

**Run 2 → 3: identifiers live in metadata, not text.** ASRS narratives say "SFO" or "San
Francisco", never "KSFO"; the ICAO code is a filter, not a search term. And a two-term OR query
(`runway | 28`) is dominated by the common word — for ≤ 4 terms every term must match. Lexical
P@10 went 0.13 → 0.75. Dense-only stays at 0.54: it finds *runway-related* chunks at the airport
but not the specific runway about half the time. That is the exact-identifier weakness hybrid
retrieval exists to cover, now with a number on it.

**Run 5: a bigger candidate pool is not the answer.** With 100 candidates per channel, hybrid
without rerank gains a little (nDCG@10 0.379 → 0.388, Recall@20 0.553 → 0.580) but hybrid+rerank
gets slightly *worse* (0.405 → 0.391): the reranker is handed more noise to promote, and latency
doubles (p50 1.4 s → 2.7 s). Recall@20 does not move. So the ceiling is not the pool — for roughly
40% of synopsis queries the target narrative is not in the top 100 chunks of either channel. That
points at the embedder. Kept at 40.

**Run 6: same quality, a quarter of the latency — and the dense channel had been exact by
accident.** The latency pass (`evals/latency/RESULTS.md`) found that the shared `pool` CTE was
materialised, so both channels sequentially scanned the corpus; the dense channel was therefore an
*exact* kNN (sort of 200k rows on disk). Filtering each channel directly lets the dense channel use
the HNSW index, which is approximate: recall@40 against exact was 0.80 at `ef_search=100` and 0.97
at 1000, so 1000 it is. Re-running the full eval shows the cost of that approximation: dense
nDCG@10 0.315 → 0.310, and after fusion and reranking nothing measurable (0.405 → 0.402, Recall@20
unchanged at 0.607, identifier P@10 0.772 → 0.774). Dense p50 472 → 46 ms, hybrid 631 → 266 ms,
hybrid+rerank 1405 → 1100 ms; the reranker is now most of the cost.

**Still open.** The measured upgrade path is now the embedder: `bge-large-en-v1.5` or `bge-m3`,
re-embed the corpus (~1–2 h), re-run. Recall@20 is the number to watch.
