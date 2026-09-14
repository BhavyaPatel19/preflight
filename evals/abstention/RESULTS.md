# Abstention evaluation

Run `258942f` at 2026-09-14T18:12:59+00:00 · 26 constructed cases, 20 with a data gap · synthetic route KZZY → KZZX alt KZZW, every case rolled back

**Recall on data-gap cases: 1.000** · **false-abstention rate: 0.000**

| gap | cases | expected abstention present | spurious abstention |
|---|---:|---:|---:|
| none | 3 | 3 | 0 |
| metar_missing | 3 | 3 | 0 |
| metar_stale | 3 | 3 | 0 |
| notams_none | 3 | 3 | 0 |
| notams_inactive | 3 | 3 | 0 |
| taf_missing | 2 | 2 | 0 |
| taf_expired | 2 | 2 | 0 |
| delay_none | 2 | 2 | 0 |
| delay_sparse | 2 | 2 | 0 |
| parse_failure | 1 | 1 | 0 |
| precedent_unavailable | 1 | 1 | 0 |
| everything | 1 | 1 | 0 |

Reasons in the schema that no rule emits yet: `conflicting_sources`. They are in the case set's vocabulary, not its cases; a rule that emits one gets its cases here.

What this measures: whether each *known* kind of data gap produces its abstention, and whether a complete data set produces none. What it does not: gaps the system has no rule for — those are silent by construction, and the time-travel eval's coverage number is where they would surface.
