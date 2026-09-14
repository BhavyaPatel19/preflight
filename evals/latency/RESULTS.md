# Latency

`preflight bench KSFO KJFK --off-block 2026-09-11T02:30Z --runs 3 --llm` — 4 findings, 3 of them
actionable (precedent search + query rewrite), narrative on every finding, 3 timed runs after a
warm-up. MacBook Pro M5 24 GB; `qwen3:14b` via Ollama; retrieval and NLI models on MPS; native
Postgres 17 on the same machine. Wall milliseconds per graph node.

## Result

| stage | before p50 | before p95 | after p50 | after p95 |
|---|---:|---:|---:|---:|
| gather | 50 | 66 | 3 | 8 |
| precedent | 27,059 | 27,914 | 12,383 | 15,253 |
| verify | 49 | 62 | 43 | 45 |
| narrate | 23,591 | 25,332 | 11,473 | 14,834 |
| **total** | **49,516** | **53,243** | **25,357** | **26,218** |

Without the model (deterministic core + precedent, what the API serves by default): precedent
8,713 ms p50 → **2,544 ms**; whole briefing 2.6 s p50, 4.0 s p95.

The target in the README is p95 ≤ 25 s for a full briefing. 26.2 s is close and honest; the rest
of this file says where the remaining time is.

## What moved it, in order of surprise

**1. The retrieval SQL was doing a sequential scan and sort of the whole corpus.** The hybrid
query filtered `chunks` in a shared `pool` CTE that both channels read. Postgres materialises a
CTE referenced twice, so neither channel could reach its index: the dense channel sorted 200k
rows by cosine distance on disk (2.2 s), and the lexical channel scanned the same CTE (0.6 s).
Each channel now filters `chunks` directly, and only the filters that were requested are in the
SQL, so the planner sees plain predicates. The dense channel became an HNSW index scan.

That made the search *approximate*, which had to be measured, not assumed. Against exact kNN on
35 golden queries, recall@40 was 0.80 at `hnsw.ef_search=100`, 0.93 at 400 and 0.97 at 1000; the
index scan at 1000 still costs ~50 ms. `iterative_scan = relaxed_order` is on so that a filtered
scan keeps going until 40 rows pass the airport filter, instead of returning whatever survives of
the first `ef_search` candidates. Then the full retrieval eval was re-run (run 6 in
[`evals/retrieval/HISTORY.md`](../retrieval/HISTORY.md)): hybrid+rerank nDCG@10 0.405 → 0.402,
Recall@20 0.607 → 0.607, identifier P@10 0.772 → 0.774 — unchanged within noise — while dense
p50 went 472 → 46 ms and hybrid 631 → 266 ms.

**2. The lexical channel was I/O-bound.** A long OR query matches ~100k chunks, and `ts_rank`
needs each one's tsvector — 1.1 GB of TOAST — on every query. With Postgres's default 128 MB
`shared_buffers`, and Ollama holding 11 GB of the machine's 24, those pages were re-read from
disk each time: 1.7 s per query, and the same query took 133 ms once the pages were resident.
`make db-start` now starts the server with `shared_buffers=2GB`. This is why precedent-only
dropped 8.7 s → 2.5 s: three searches, each ~0.3 s of SQL and ~0.7 s of reranking.

**3. Concurrency only helps if the model server batches.** First measurement, with a default
`ollama serve`: 1, 2 and 4 concurrent requests gave 12.8, 13.4 and 13.5 tokens/s *aggregate* —
per-request latency grew linearly, and parallelising the calls would have gained nothing. With
`OLLAMA_NUM_PARALLEL=4` the same test gave 13.5, 23.2 and 31.2 tok/s. So the per-finding model
calls — three query rewrites, four narratives — are now issued together
(`PREFLIGHT_LLM_CONCURRENCY`, default 4, `fan_out` in `preflight.llm`), and `make ollama-start`
sets the server flag. Narrate went 23.6 s → 11.5 s. Ollama's resident size grew from 9.3 to
11.4 GB for the extra KV cache.

**4. One verifier batch instead of one per finding.** Narrative sentences from every finding go
to the NLI model in a single `entailment` call; the gating and per-finding bookkeeping are
unchanged (tests: `test_narrative_verifies_all_findings_in_one_batch`). Small on its own — the
verifier was already fast — but it means narrate is now one round of model calls plus one
verifier call, whatever the finding count.

## Where the remaining 25 s is

- **Narrate (11.5 s)**: four concurrent `qwen3:14b` calls, ~260 output tokens each at ~8 tok/s
  per stream when four share the GPU. Levers, none free: a smaller model for narrative
  (`qwen3:8b`), fewer sentences, or skipping INFO findings. Each changes the narrative eval's
  inputs and would be re-measured there.
- **Precedent (12.4 s)**: ~6 s of concurrent query rewrites (prompt evaluation dominates — the
  finding's data block is ~400 tokens), then three searches at ~1 s each, of which 0.7 s is
  reranking 40 candidates. Reranking across findings in one batch, or a smaller candidate set for
  the reranker, are the next measurements. The rewrites could also overlap the first search.
- **Lexical channel**: proportional to matched rows. Pruning a long OR query to its rarest terms
  would cut both matches and, plausibly, noise — but it is a retrieval change and belongs to the
  retrieval eval, not here.

## Reproduce

```bash
make db-start ollama-start                              # 2 GB shared_buffers; OLLAMA_NUM_PARALLEL=4
preflight bench KSFO KJFK --off-block 2026-09-11T02:30Z --runs 3 --llm
preflight bench KSFO KJFK --off-block 2026-09-11T02:30Z --runs 3          # no model
```
