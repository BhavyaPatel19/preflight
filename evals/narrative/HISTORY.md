# Narrative evaluation — run history

Model: `ollama/qwen3:14b` (local, zero cost) throughout. Same 26 findings each run: NOTAM findings
from the realistic fixture set, plus one weather and one delay finding for each of ten watchlist
airports. `RESULTS.md` is the latest run; the dropped sentences are listed there in full.

| # | date | unsupported rate | generated / kept / dropped | what changed |
|---|---|---:|---:|---|
| 1 | 2026-09-13 | **0.500** | 108 / 54 / 54 | baseline: prompt asked what the finding "means for the flight"; verifier = NLI only |
| 2 | 2026-09-13 | **0.224** | 107 / 83 / 24 | prompt restricted to facts (no advice, predictions, or "should"); NOTAM premise carries a synonym glossary (*unserviceable = not working*) |
| 3 | 2026-09-13 | **0.010** | 99 / 98 / 1 | evidence identifies itself ("NOTAM A2004/26 at KORD states: …"); delay evidence states the 80% band and the climatology caveat in the claim's own terms; verifier becomes a **hybrid** — NLI plus an exact-figure gate |

## What each run taught

**Run 1 — the model gave advice, and the verifier was right to drop it.** Almost every dropped
sentence was "flights should plan alternative taxi routes" or "crews may need to use alternate
procedures": plausible, unsourced, and exactly what a safety-adjacent briefing must not emit.
Half the model's output was out of scope because the prompt invited it. Not a verifier problem.

**Run 2 — the evidence didn't say what the claims said.** The core delay claim ends "Climatology,
not a forecast"; the model faithfully echoed it; the citation's quote never contained those words,
so the echo was rejected. NOTAM restatements framed as "a NOTAM states that …" were rejected
because the premise didn't identify itself as a NOTAM. Both fixed on the evidence side, not by
loosening the check.

**Run 3 — and the fix exposed the verifier's real weakness.** Once the delay evidence and claims
shared their caveat sentence, the NLI model scored a *corrupted* median ("44 min" against evidence
saying −1) at 0.98: with enough matching prose, it stops reading the numbers. The grounding eval
caught it (corruption rejection fell from 1.000 to 0.444). The verifier is now a hybrid: NLI for
meaning, plus every figure in a claim must appear in its evidence. Grounding rejection is back to
0.972 (the residual is a corrupted figure that coincidentally equals another number in the same
evidence — the known limit of exact matching), and the narrative rate is 0.01 with one genuine
catch: "80% of arrivals" where the evidence says "80% of hours".

## What the number means

For **constrained restatement** — plain-language sentences over cited facts, no advice — a local
14B model is essentially as reliable as anything: one misstatement in 99 sentences, caught. The
frontier-model comparison row (`PREFLIGHT_LLM=anthropic`, same command) would measure the same
task. The open question is not whether a bigger model restates facts better; it is the *judge*
(Sprint 5), where judgment rather than restatement is the job.
