# Precedent-relevance evaluation

Run `94e158c` at 2026-09-14T04:40:01+00:00 · judge `ollama/qwen3:14b` · 304 of 304 (hazard, prior report) pairs judged · attachment threshold 0.5

## Judge-estimated — unvalidated until the sheet is filled

| set | n | judge says relevant |
|---|---:|---:|
| attached to briefings (score ≥ 0.5) | 195 | 0.713 |
| below threshold (not attached) | 109 | 0.606 |

| reranker score | n | judge relevant |
|---|---:|---:|
| 0.0–0.3 | 46 | 0.522 |
| 0.3–0.5 | 63 | 0.667 |
| 0.5–0.7 | 82 | 0.732 |
| 0.7–1.0 | 113 | 0.699 |

| hazard source | n | judge relevant |
|---|---:|---:|
| fixture-notam | 64 | 0.578 |
| ntsb-case | 240 | 0.700 |

A note on the judge itself: it calls 52% of pairs relevant even when the reranker scored them
below 0.3. Either the reranker under-rates true precedent, or this local 14B judge is lenient.
The human sheet is the only thing that can tell those apart.

## Human validation

`evals/precedent/labels.csv` has 0 of 100 rows labelled. Fill the `relevant_precedent (y/n)` column and run `preflight eval precedent --score`.
Until then the judge is an unvalidated instrument and the numbers above are estimates, not results.

κ above 0.6 is substantial agreement; the README target is ≥ 0.7. The judge is a
local 14B model; a frontier judge would be measured the same way.
