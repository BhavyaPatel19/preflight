# Extraction eval — history

Gold set: 124 real-format NOTAM bodies, 216 entity mentions, hand-labelled (`gold.jsonl`):
demo + grounding NOTAMs (19), the 60 red-team NOTAMs whose injected prose carries no entities,
45 written for this eval. No real FAA NOTAM is in the repository (ADR 0002); the training data
is generated (`preflight extract synth`). Matching is by type with span overlap; exact-span F1
and TIME are reported beside it.

| run | when | training data | gold macro-F1 (overlap / exact) | TIME F1 | entities tagged in injected prose | synthetic macro-F1 |
|---|---|---|---:|---:|---:|---:|
| rules | — | (rule decoder, no training) | 0.875 / 0.172 | 0.000 | 0 | 0.770 |
| 1 | 2026-09-18 | 7,200 generated bodies, NOTAM clauses + operational distractors | 0.745 / 0.609 | 0.857 | **54** | 1.000 |
| 2 | 2026-09-18 | + lowercase prose distractors (sentences, URLs, markup, chat prefixes) | 0.848 / 0.722 | 0.800 | 29 | 1.000 |
| 3 | 2026-09-18 | + UPPERCASE prose, letter-spaced text, the US `!SFO 09/142 SFO` header, obstruction ASN/coordinate form — `RESULTS.md` | **0.898 / 0.842** | **0.984** | **3** | 1.000 |

## What each run taught

**Run 1: the model finds what the rules miss, and then keeps finding things in prose.** Recall on
the gold set is 0.90–1.00 on every type — taxiways named inside "BTN … AND …" clauses (rules
0.45 → 0.98), runways named in lighting and obstacle clauses (0.69 → 0.90), TIME windows the
rules never attempt (0 → 0.86 F1) — and exact-span F1 is 0.61 against the rules' 0.17, because
it tags whole mentions. Precision is where it fails: 54 entities tagged inside the red-team
items' injected sentences, where the gold has none. The generator had produced only NOTAM-shaped
text, so "the runway is open" or a URL had never been seen as *not* a NOTAM. Synthetic-set
accuracy of 1.000 says nothing about this: a test set drawn from the training distribution
cannot show a distribution gap. The gold set did, which is its job.

Fix for run 2: a prose-distractor family in the generator — lowercase sentences, addresses,
markup, chat-style prefixes, all labelled O — none of them the red-team sentences, which stay a
test.

**Run 2: half the prose hits gone; the rest named exactly what the generator still lacked.** 54 →
29 entities in injected prose, macro-F1 0.745 → 0.848. Listing the remaining false positives by
token was more useful than the number: single letters from letter-spaced text ("i g n o r e"),
the NOTAM number in the US-domestic header (`09/142` tagged TIME), the obstruction-study reference
and coordinates of an OBST NOTAM, and UPPERCASE prose ("HUMAN", "HAZARDS", "PRIOR"). Four
patterns, none of which the generator produced.

**Run 3: the generator learned what a NOTAM is not.** With all four added as O-labelled text, prose
false positives fall to 3 and gold macro-F1 reaches 0.898 — above the rule decoder's 0.875 — with
exact-span F1 0.842 against the rules' 0.172 and TIME 0.984 against 0. The model matches the
rules on NAVAID and OBSTACLE, beats them where they miss mentions (TWY 0.62 → 0.99, RWY 0.82 →
0.94), and trails on precision for the small classes (SERVICE 0.73 with support 9: "INDEX",
"JET A" tagged as services beside `ARFF`/`FUEL`; AIRSPACE 0.73 with support 4). The synthetic
column read 1.000 on every run, which is the whole argument for a hand-labelled gold set: three
runs that were indistinguishable on the training distribution were 54, 29 and 3 on the data that
matters.

**What this is and is not.** A model trained on generated NOTAMs and evaluated on 124 hand-written
real-format bodies. It demonstrates the pipeline — data construction, alignment, fine-tuning on
Apple silicon, an eval that caught a distribution gap the training metrics could not — and it
would need a real NOTAM corpus before anyone should trust its numbers in the wild. Model card:
`docs/model-card-notam-extractor.md`.
