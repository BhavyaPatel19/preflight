# Briefing evaluation (time-travel)

Run `15d19b8` at 2026-11-10T08:53:26+00:00 · 300 positives (NTSB events 2008-01-02 → 2026-06-20) + 300 matched negatives.

| metric | value |
|---|---:|
| covered positives (data exists for the snapshot) | 119 / 300 |
| covered negatives | 119 / 300 |
| implicated-hazard recall (covered positives) | 0.269 |
| false-alarm rate (covered negatives) | 0.160 |

| implicated category | cases | covered | found | recall | matched negatives covered | false alarms |
|---|---:|---:|---:|---:|---:|---:|
| lighting | 26 | 0 | 0 | — | 0 | — |
| runway | 57 | 0 | 0 | — | 0 | — |
| weather | 142 | 119 | 32 | 0.269 | 119 | 0.160 |
| wildlife | 75 | 0 | 0 | — | 0 | — |

**The wind rule, priced** (119 covered weather positives, 119 matched negatives; each row flags gust ≥ g or wind ≥ w):

| gust ≥ kt | wind ≥ kt | recall | false-alarm rate |
|---:|---:|---:|---:|
| 25 | 20 | 0.025 | 0.034 | ←
| 20 | 17 | 0.109 | 0.084 |
| 18 | 15 | 0.151 | 0.092 |
| 15 | 12 | 0.286 | 0.143 |
| 12 | 10 | 0.370 | 0.218 |

75 of 119 positives had no gust and under 10 kt of wind in the METAR an hour before the event (median wind: positives 7 kt, negatives 5 kt). For those, the hazard the NTSB named was not in the airport observation at briefing time, whatever the threshold — the ceiling of a METAR-based weather layer for light-aircraft wind accidents.

Coverage is the honest number here. The weather slice is covered from the Iowa State archives — public historical METARs, and the TAFs in force, pulled for each case's airport at its snapshot (`preflight eval briefing --backfill-weather`). The wildlife, runway and lighting slices need the NOTAMs in force at the time, and live NOTAM feeds are out of scope by choice (ADR 0002), so those cases stay uncovered and are reported, not scored. Recall and false-alarm rate are computed only over covered cases.
