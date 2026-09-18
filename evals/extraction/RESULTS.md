# Entity extraction evaluation

Run `c536f35` at 2026-09-18T07:07:00+00:00 · gold: 124 real-format NOTAM bodies, 216 entity mentions, hand-labelled (`evals/extraction/gold.jsonl`) · synthetic validation: 800 generated bodies

| system | data | macro-F1 (8 entity types, overlap) | macro-F1 (exact span) | TIME F1 | entities tagged in injected prose |
|---|---|---:|---:|---:|---:|
| rules | gold | 0.875 | 0.172 | 0.000 | 0 |
| rules | synthetic | 0.770 | 0.203 | 0.000 | — |

**Per type on the gold set** (overlap match; P / R / F1 · support):

| type | rules |
|---|---:|
| RWY | 1.000 / 0.694 / 0.819 · 49 |
| TWY | 1.000 / 0.447 / 0.618 · 47 |
| NAVAID | 0.970 / 1.000 / 0.985 · 32 |
| LIGHTING | 1.000 / 1.000 / 1.000 · 26 |
| OBSTACLE | 1.000 / 0.909 / 0.952 · 11 |
| AIRSPACE | 0.750 / 0.750 / 0.750 · 4 |
| SERVICE | 1.000 / 0.889 / 0.941 · 9 |
| APRON | 1.000 / 0.875 / 0.933 · 8 |
| TIME | — / 0.000 / 0.000 · 30 |

The gold set is the number that counts: real formats, hand labels, and 60 items whose prose is an attack on the reader. The synthetic column says only how well a system fits the generator's distribution. The rule decoder marks identifiers rather than whole mentions and does not tag TIME, which is what the overlap/exact split and the TIME column show. No real FAA NOTAM is in either set (ADR 0002).
