# ADR 0002 — NOTAM access is gated; build against a provider interface and archive forward

**Status:** accepted · **Date:** 2026-09-11

## Context

The project plan assumed the FAA NOTAM API was a free registration away. It is not:

| Attempt | Result |
|---|---|
| FAA NOTAM Management Service API (`api.faa.gov`) | Not self-serve. Access is requested by email and eligibility is restricted by regulation to operators and approved parties. Denied for an individual research project. |
| FAA NOTAM Search (`notams.aim.faa.gov`) | The public web UI works for a human. A programmatic request to the endpoint behind it returns **403**. We treat that as an explicit "no" and do not disguise requests to get around it. |
| DoD Internet NOTAM Service (DINS) | Hostname no longer resolves. Retired. |
| ICAO API Data Service | Has realtime and stored NOTAM endpoints, but 25 free calls on registration; paid beyond that. A trial, not a feed. |
| NASA Digital Information Platform | NASA redistributes the public FAA SWIM NOTAM feed as structured JSON (NTRS 20250003355, distribution: public). Access is by request. **Requested 2026-09-11.** |

NOTAM *data* is public domain (US government work). *Access* to it is not open. That distinction is the whole problem.

## Decision

1. **Ingestion is written against a `NotamSource` protocol**, not a client. Providers are plugs: `FileSource` (text dumps — manual exports, fixtures, our own archive) works today; `NasaDipSource` is a loud stub that gets implemented against an observed response once a token exists, exactly as the aviationweather client was. No provider's shape is guessed from documentation.

2. **Every fetch is archived before it is decoded** (`preflight.archive`). Nobody hands out historical NOTAMs, and the time-travel evaluation needs them. From today the project keeps its own history: raw payload, provider, and the instant it was fetched. A parser bug must never cost a snapshot, so archive precedes decode.

3. **The seed corpus for the Sprint 2 extractor is collected by hand** from the public FAA search UI — a few dozen large airports, saved as text into `data/raw/notams/manual/`. Tedious, unambiguous, and enough (a few thousand NOTAMs) to fine-tune on.

## Consequences

- The evaluation design changes shape. **Negative controls** (uneventful flights) come from our own archive, so they accrue only from today forward. **Positive cases** older than the archive must come from NTSB docket exhibits, which routinely include the NOTAMs in effect at the time of an accident — public, specific, and already tied to a finding. The golden set becomes "NTSB-docket positives + archive-era positives and negatives", and the README says so.
- The demo runs on a dump or the archive until NASA DIP access lands. That is acceptable: the briefing logic is identical, and honesty about the source is part of the product.
- If DIP access is refused, the fallbacks are the ICAO paid tier (small budget, international coverage) or continuing on manual collection. Either keeps the pipeline unchanged above the source boundary.

## Revisit when

- NASA DIP access is granted → implement `NasaDipSource` from an observed response; schedule it hourly; the archive starts filling itself.
- The FAA opens self-serve access → add a provider. Nothing else changes.
