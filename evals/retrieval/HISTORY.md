# Retrieval evaluation — run history

One line per run that changed something. `RESULTS.md` is always the latest full run; the JSON
for every run is under `runs/` (gitignored — the numbers that matter are here).

| # | date (UTC) | code | database | change under test | dense nDCG@10 | lexical nDCG@10 | hybrid nDCG@10 | hybrid+rerank nDCG@10 | identifier P@10 (lexical / hybrid+rerank) | lexical p50 |
|---|---|---|---|---|---:|---:|---:|---:|---:|---:|
| 1 | 2026-09-12 17:57 | `c45044f` | pg16 in Colima | **baseline** — `ts_rank_cd`, OR-joined terms, identifier queries with the ICAO as query text | 0.315 | 0.105 | 0.266 | 0.390 | 0.016 / 0.080 | 856 ms |
| 2 | 2026-09-12 18:42 | step 11 | pg17 native | `ts_rank` instead of `ts_rank_cd`; identifier queries use the airport as a metadata filter; `dense+rerank` added | 0.315 | **0.294** | **0.379** | **0.405** | 0.134 / 0.100 | 421 ms |
| 3 | 2026-09-12 18:48 | step 11 | pg17 native | AND-semantics for ≤ 4-term queries; strict airport filter for identifier queries | — | — | — | — | **0.746 / 0.774** | — |
| 4 | 2026-09-12 19:11 | step 11 | pg17 native | **final full run** at the step-11 retrieval code (recorded sha is the step-12 checkout; retrieval code identical) — `RESULTS.md` | 0.315 | 0.294 | 0.379 | **0.405** | 0.746 / 0.772 | 424 ms |

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

**Still open.** Recall@20 tops out around 0.6 with 40 candidates per channel; the reranker cannot
recover what the pool never held. Candidate-pool size is the next knob (`--candidates 100`).
`bge-m3` remains the untested upgrade path.
