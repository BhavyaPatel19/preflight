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

**Run 4 (pre-registered 2026-11-11, before any rebuild): close the time-travel leak.** Precedent
search now keeps only reports dated strictly before the briefing's UTC day
(`Retriever.search(published_before=…)`; an NTSB case is briefed at its snapshot, a test NOTAM at
its effective time). On the same 30 held-out hazards: rebuild the pool with
`preflight eval precedent --test-build`, which keeps every existing label. Pairs new to the pool
are labelled blind by Claude under the run-3 criterion, from the hazard and report text alone,
before scoring. Pass rule for the mechanism check: **precision ≥ 0.90 and relevant precedent per
hazard ≥ 2.6.** A miss by any margin is a miss. If it fails, the filter stays anyway (it removes a
leak, it is not tuned), and the README reports the new number in place of 0.911.

*Result (2026-11-12):* **failed.** The rebuild kept 72 of the 103 labelled pairs, dropped 31 and
added 34 (the filter changes the candidate pool for every NTSB case, not only the leaked row); the
34 were labelled blind before scoring. The Pullman self-citation is gone.

| 30 held-out hazards, reports dated before the briefing | old rule (score ≥ 0.5) | mechanism check |
|---|---:|---:|
| precision of attached precedent (95% Wilson) | 0.756 (0.65–0.84) | **0.811** (0.72–0.88) |
| relevant precedent per hazard | 2.07 | **2.43** |
| irrelevant reports attached | 20 / 82 | **17 / 90** |
| hazards with nothing attached | 2 | 0 |
| NOTAM hazards (14) · NTSB cases (16), precision | 0.789 · 0.727 | 0.881 · 0.750 |

Gate minus old rule: +0.055, 95% bootstrap interval over hazards −0.06 to +0.18; the gate still
attaches more relevant precedent, but on this pool the precision gain is within noise. Both
conditions of the rule missed (0.811 < 0.90; 2.43 < 2.6). The filter stays, as pre-registered: it
removes reports a briefing could not have had. The honest reading of run 3 is that part of its
0.911 came from reports published after the hazard, including the briefed accident itself. The
NTSB cases are the hard half: for a 2008–2010 event almost nothing in the corpus predates it.

The README precedent row now reads 0.81. Labels are still Claude's; the 20-row human audit
(`test/labels.csv`) applies to this sheet.

