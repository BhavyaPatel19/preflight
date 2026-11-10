# Precedent relevance: history

**Run 1 (2026-09-14): judge only.** `qwen3:14b` judged 304 (hazard, attached report) pairs;
it called 71% of attached precedents relevant. The 100-row sheet (`labels.csv`) was left
for a human, because an LLM judge nobody has checked is not a measurement.

**Run 2 (2026-11-10): the sheet labelled by Claude, not by a human.** `labels_claude.csv` holds
Claude's (`claude-opus-5-5`) label and one-line reason for each of the 100 rows. It was
labelled blind: from the sheet's hazard and report text only, without the judge's verdicts or
the reranker scores, under the criterion in `README.md`. Rows that show two passages of the same
report were labelled at the report level. This is a second model's careful reading. **It is not
human validation**, and `summary.json` still records 0 human labels and no κ.

| on 98 unique pairs (pipeline of run 1: base embedder, stock reranker) | value |
|---|---:|
| relevant, attached to the briefing (reranker ≥ 0.5) | **0.42** (20 / 48) |
| relevant, not attached (reranker < 0.5) | 0.42 (21 / 50) |
| κ, qwen3:14b judge vs Claude's labels | **0.54** (agreement 0.77) |
| judge says relevant / Claude says not | 19 of the 23 disagreements |

By reranker score: 0.0–0.3 → 0.25, 0.3–0.5 → 0.53, 0.5–0.7 → 0.21, 0.7–1.0 → 0.55. By hazard
source: NOTAM fixtures 0.42, NTSB cases 0.42.

What this says, if a human audit confirms it:

- **Fewer than half of the precedents a briefing attaches are relevant.** The judge's 0.71 was
  inflated by a lenient judge (it said relevant 57% of the time vs 42%).
- **The 0.5 reranker threshold does not separate relevant from irrelevant.** Precision is the
  same above and below it, and it is not monotonic in score. The stock cross-encoder scores
  topical similarity (same airport feature, same phase of flight), not whether a report is
  precedent for this hazard. Most misses are same-topic, different-mechanism: a PAPI outage
  matched to a collision *with* runway lights, a wildlife hazard matched to a landing flare with
  no animal involved.
- **The 14B judge is not yet a trustworthy instrument** (κ 0.54 < 0.70 target), even before a
  human is involved.

**Known defect:** a pair id is `source-case-<report>`, so two passages of one report under the same
hazard share an id (304 pairs, 299 ids). The judge verdicts and labels collapse them. Fix the id
before the next judged run.

**Next:** (1) a 20-row blind human audit of these labels, which turns this into a human-anchored
number; (2) rebuild the pairs with the current pipeline (fine-tuned embedder, then the
fine-tuned reranker of retrieval run 11), and judge them with a stronger judge measured against
this sheet first.
