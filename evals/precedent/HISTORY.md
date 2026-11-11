# Precedent relevance: history

**Run 1 (2026-09-14): judge only.** `qwen3:14b` judged 304 (hazard, attached report) pairs and
called 71% of attached precedent relevant. The 100-row sheet (`labels.csv`) was left for a human.

**Run 2 (2026-11-10): the sheet labelled by Claude. This became the dev set.**
`labels_claude.csv` holds Claude's (`claude-opus-5-5`) label and a one-line reason per row,
labelled blind from the hazard and report text (no judge verdicts, no reranker scores). It is not
human validation; `labels.csv` and `summary.json` still record 0 human labels. On the 98 unique
pairs (run-1 pipeline: base embedder, stock reranker, qwen-rewritten queries):

| | value |
|---|---:|
| relevant among attached (reranker ≥ 0.5) | 0.42 |
| relevant among not attached (< 0.5) | 0.42 |
| κ, qwen3:14b judge vs Claude | 0.54 (19 of 23 disagreements: judge more lenient) |

The reranker threshold did not separate relevant from irrelevant precedent. Nearly every
irrelevant pair was a report that does not involve the hazard's mechanism at all: a wildlife
hazard matched to a landing flare with no animal, a PAPI outage matched to a crash *into* runway
lights, a runway closure matched to a generic overrun.

**Run 3 (2026-11-11): a mechanism check replaces the score threshold.** `brief/mechanism.py`
maps each hazard to its mechanism (wildlife, incursion, runway condition, closure, taxi route,
approach guidance, visual glidepath, airport/aircraft lighting, obstruction, navaid, airspace,
ramp) and attaches a report only if its title or passage contains that mechanism's words. The
retriever is asked for 15 hits instead of 9 so the gate has room. Designed on the dev set only
(in-sample: precision 0.42 → 0.77 at 0.98 of relevant kept; adding the score threshold back made
it worse, 0.68).

*Test, written down before it was built:* 30 hazards absent from the dev set (14 new NOTAMs at
other airports in `evals/precedent_test_notams.py`, 16 NTSB cases after the dev 60), both rules
run on the same ranked hits with the deterministic query templates, every attached pair on one
shuffled sheet with no rule named (`test/labels.csv`, 103 pairs), labelled blind by Claude under
the same criterion. Pass rule: precision ≥ 0.65 and relevant precedent per hazard ≥ 90% of the
old rule's.

| 30 held-out hazards, current pipeline (fine-tuned embedder) | old rule (score ≥ 0.5) | mechanism check |
|---|---:|---:|
| precision of attached precedent | 0.816 | **0.911** |
| relevant precedent per hazard | 2.37 | **2.73** |
| irrelevant reports attached | 16 / 87 | **8 / 90** |
| hazards with nothing attached | 0 | 0 |

Both conditions met. Precision gain +0.095, 95% bootstrap interval over hazards +0.024 to +0.186.
NOTAM hazards 0.795 → 0.905, NTSB cases 0.833 → 0.917.

How to read it:

- **The old rule is far better here than in run 2** (0.82 vs 0.42). That comparison is not like for
  like: different hazards, the fine-tuned embedder (retrieval run 10), and template queries
  instead of LLM rewrites. The gate's own effect is the paired comparison in the table: half the
  irrelevant attachments, 15% more relevant ones.
- **Labels are Claude's, not a human's**, and the labeller also wrote the mechanism lexicon, so its
  idea of relevance and the gate's are related. A 20-row blind human audit of `test/labels.csv`
  is the check on that.
- **Known leak, both rules equally:** the briefed NTSB accident can be retrieved as its own
  precedent (one test row, Pullman). Precedent search should exclude reports dated after the
  briefing time; not fixed here.
- **Known defect, run 1 pairs:** a pair id was `hash()` of (hazard, report), salted per process and
  shared by two passages of one report (304 pairs, 299 ids). The test set uses a stable SHA-256 id.

Reproduce: `preflight eval precedent --test-build` (needs the corpus and models), label the sheet,
`preflight eval precedent --test-score`.
