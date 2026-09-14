# Abstention eval — design and history

`preflight eval abstention` builds 26 briefings on a synthetic route (KZZY → KZZX, alternate
KZZW), each inside a transaction it rolls back. The database state is set up per case: every
source present and fresh, then one gap applied — a METAR three hours old, no TAF across the
arrival window, an airport the archive has never fetched, fewer than four weeks of delay history,
a fetch in which the decoder rejected NOTAMs, no retrieval models — and the briefing must carry
exactly that gap's abstention and no other. Latest numbers: [`RESULTS.md`](RESULTS.md).

**Recall** (gap cases where the expected abstention appears) is the README row. **False-abstention
rate** (cases with an abstention nobody asked for; the three clean cases and the two
NOTAMs-on-record-but-none-in-force cases are the sharpest) is the guard against making recall
easy by abstaining about everything.

## History

Writing the case set exposed three gaps the briefing was silent about, and silent is the failure
mode this system exists to avoid — a briefing with no NOTAM findings reads as "no hazards" whether
the archive is clean or empty:

| gap | before | rule added |
|---|---|---|
| airport never fetched (no NOTAM on record at all) | no finding, no abstention | `{icao} NOTAMs · no_coverage` — distinct from NOTAMs on record but none in force, which stays silent |
| no delay history for a destination or alternate | delay finding simply absent | `{icao} arrival delay · no_coverage` (also when the history has fewer than 4 matching hours) |
| decoder rejected NOTAMs in the latest fetch | counted in the ingest run, never surfaced | `NOTAM decoding · parse_failure`, once per briefing, with the count and fetch time |

Against the rules as they were, 11 of the 20 gap cases pass (0.55): METAR missing/stale, TAF
missing/expired and retrieval-unavailable were already abstentions. With the three rules, 20 of 20,
and the six no-gap cases stay clean.

`conflicting_sources` is in the schema and in no rule: nothing in the current pipeline detects two
sources disagreeing. It is listed in the results as never emitted rather than dropped from the
vocabulary, so that a rule for it lands with its cases.

## What it does not measure

Gaps the system has no rule for are silent by construction and cannot appear here. The
time-travel briefing eval's coverage number (`evals/briefing/RESULTS.md`) is where unknown gaps
surface: a case the archive cannot brief is a gap the rules did not name.
