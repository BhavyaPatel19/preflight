# Briefing evaluation (time-travel)

Run `2f80faf` at 2026-09-12T19:35:22+00:00 · 300 positives (NTSB events 2008-01-02 → 2026-06-20) + 300 matched negatives.

| metric | value |
|---|---:|
| covered positives (data exists for the snapshot) | 0 / 300 |
| covered negatives | 0 / 300 |
| implicated-hazard recall (covered positives) | — |
| false-alarm rate (covered negatives) | — |

| implicated category | cases | covered | found |
|---|---:|---:|---:|
| lighting | 26 | 0 | 0 |
| runway | 57 | 0 | 0 |
| weather | 142 | 0 | 0 |
| wildlife | 75 | 0 | 0 |

Coverage is the honest number here: the raw NOTAM/weather archive began on 2026-09-11, so historical cases are uncovered until their snapshot data is reconstructed (NTSB docket exhibits) or new events occur inside the archive. Recall and false-alarm rate are computed only over covered cases and are the CI gate's inputs once coverage is non-trivial.
