# Model card — `notam-extractor` (ModernBERT-base, token classification)

**What it does.** Tags entity mentions in a NOTAM body: `RWY`, `TWY`, `NAVAID`, `LIGHTING`,
`OBSTACLE`, `AIRSPACE`, `SERVICE`, `APRON`, and `TIME` (validity windows and schedules), as BIO
tags over whitespace/punctuation tokens. It is the "small model" tier of the decode cascade
(rules → small model → LLM) described in the README, and it produces the same `Entity` shape the
rule decoder does.

**What it was trained on — read this first.** *Generated* NOTAMs. Real NOTAM feeds require an
account and approval and are out of scope for this project by choice (ADR 0002), so the training
set is 7,200 bodies produced by `preflight extract synth`: clause templates over the Q-code
subjects and the FAA/ICAO contraction vocabulary, ICAO and US-domestic framing, operational
distractor clauses, and — after the first evaluation showed why — natural-language, UPPERCASE,
letter-spaced and web/markup prose labelled as nothing. The generator is deterministic and in the
repository; the labels are correct by construction.

**What it was evaluated on.** Two sets, never blended:

- **Gold** — 124 real-format NOTAM bodies written by hand in the repository (demo and grounding
  NOTAMs, the 60 red-team NOTAMs whose injected prose must produce no entities, and 45 authored to
  widen the vocabulary), hand-labelled with the mention convention *type keyword + identifier*
  (`RWY 28R`, `ILS RWY 22L`, `OBST CRANE`, `DLY 0600-1400`). This is the number that matters.
- **Synthetic validation** — 800 generated bodies. Says only how well the model fits its own
  training distribution.

Numbers, per run, are in [`evals/extraction/HISTORY.md`](../evals/extraction/HISTORY.md); the
latest run is [`evals/extraction/RESULTS.md`](../evals/extraction/RESULTS.md). Matching is by type
with span overlap; exact-span F1 is reported beside it.

**Base model and training.** `answerdotai/ModernBERT-base` (149M), full fine-tune, AdamW 5e-5,
3 epochs, batch 32, linear warm-up/decay, on an Apple M5 (MPS) in ~12 minutes. Word-level labels
are aligned to the first sub-token; other sub-tokens are ignored. `preflight extract train`
reproduces it; `models/notam-extractor/preflight.json` records the exact configuration.

**Known limitations.**
- It has never seen a real NOTAM. Formats or phrasings absent from the generator are
  out-of-distribution, and the first two training runs showed exactly what that looks like: prose
  tagged as entities until prose was added to the training data.
- The gold set is small (124 bodies, 216 mentions) and hand-written by one person in real formats;
  per-type numbers with support under 10 (`AIRSPACE`, `SERVICE`, `APRON`) are indicative only.
- Mention boundaries follow this project's convention; another labelling convention would score
  it differently (the exact-span column is the sensitive one).
- Not for operational use. Nothing in this repository is.

**Publishing.** The weights are not committed (`models/` is git-ignored). Publishing to the Hugging
Face Hub is a one-command step for the repository owner (`hf upload`), and this card is written to
travel with the weights unchanged.
