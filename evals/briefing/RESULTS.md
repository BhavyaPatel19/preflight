# Briefing evaluation (time-travel)

Run `43195cd` at 2026-09-18T06:22:43+00:00 · 300 positives (NTSB events 2008-01-02 → 2026-06-20) + 300 matched negatives.

| metric | value |
|---|---:|
| covered positives (data exists for the snapshot) | 117 / 300 |
| covered negatives | 117 / 300 |
| implicated-hazard recall (covered positives) | 0.188 |
| false-alarm rate (covered negatives) | 0.103 |

| implicated category | cases | covered | found | recall | matched negatives covered | false alarms |
|---|---:|---:|---:|---:|---:|---:|
| lighting | 26 | 0 | 0 | — | 0 | — |
| runway | 57 | 0 | 0 | — | 0 | — |
| weather | 142 | 117 | 22 | 0.188 | 117 | 0.103 |
| wildlife | 75 | 0 | 0 | — | 0 | — |

**The wind rule, priced** (117 covered weather positives, 117 matched negatives; each row flags gust ≥ g or wind ≥ w):

| gust ≥ kt | wind ≥ kt | recall | false-alarm rate |
|---:|---:|---:|---:|
| 25 | 20 | 0.026 | 0.034 | ←
| 20 | 17 | 0.103 | 0.085 |
| 18 | 15 | 0.145 | 0.094 |
| 15 | 12 | 0.282 | 0.145 |
| 12 | 10 | 0.368 | 0.222 |

74 of 117 positives had no gust and under 10 kt of wind in the METAR an hour before the event (median wind: positives 7 kt, negatives 5 kt). For those, the hazard the NTSB named was not in the airport observation at briefing time, whatever the threshold — the ceiling of a METAR-based weather layer for light-aircraft wind accidents.

Coverage is the honest number here. The weather slice is covered from the Iowa State ASOS archive — public historical METARs pulled for each case's airport at its snapshot (`preflight eval briefing --backfill-weather`). The wildlife, runway and lighting slices need the NOTAMs in force at the time, and live NOTAM feeds are out of scope by choice (ADR 0002), so those cases stay uncovered and are reported, not scored. Recall and false-alarm rate are computed only over covered cases.
