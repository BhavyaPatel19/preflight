# Preflight

**An agentic route-risk briefing system for flight operations — every claim cited, every capability measured, and explicit about what it doesn't know.**

Give it a flight. It reads every NOTAM, weather product and relevant historical incident for that route, and returns a ranked hazard briefing where each sentence traces back to a source record.

```
$ preflight brief KSFO KJFK --off-block 2026-09-11T02:30Z --type A320
```

> [!WARNING]
> **Not for operational use.** Preflight is a research and portfolio system. It is not certified,
> not validated, and must not be used for real flight planning. It is built against public
> aeronautical data to study a hard information-retrieval problem — not to replace an official
> preflight briefing.

---

## The problem

Before every flight, a crew receives a briefing package: a wall of ALL-CAPS telegraphic text listing
every closed taxiway, unlit obstacle, out-of-service navaid and temporary flight restriction along the
route. A transcontinental package routinely runs 60–100 pages. The critical item and the trivial item
are formatted identically, sorted by nothing useful, and written in an ICAO contraction dialect that
takes years to read fluently.

This is a documented safety problem. In the NTSB's investigation of **Air Canada 759** — the 2017
near-miss where an A320 descended toward an occupied taxiway at SFO — the crew did not recall the
NOTAM announcing that the parallel runway was closed, despite it being in the package they were
issued. The FAA has had a NOTAM modernization effort running since.

So: high-volume, badly-structured, genuinely hard-to-parse text, where **missing something and crying
wolf are both failures**. That second half is the interesting part.

---

## What makes this tractable to evaluate

Most retrieval systems are graded on vibes, because there is no ground truth for "was that a good
answer?"

Preflight has one. Aviation incidents are publicly investigated after the fact. That means you can
reconstruct the data that existed **60 minutes before a documented event** and ask a question with an
objectively correct answer:

> Did the briefing surface the hazard that the investigation later found contributed?

Pair 200 of those positive cases with 200 **matched negative controls** — uneventful flights matched
on airport, hour and season — and you can measure recall and false-alarm rate on the same footing.
Alert fatigue is the real failure mode of every safety system ever fielded, so precision is not a
secondary metric here.

This eval design is the centre of the project. Everything else is in service of it.

---

## Example output

```
KSFO → KJFK  ·  A320  ·  off-block 0230Z            3 findings · 1 abstention

┌ HIGH ── RUNWAY ──────────────────────────── taxi, takeoff ──┐
│ 28R closed for work in progress until 0700Z — your entire   │
│ departure window. Expect 28L, where the PAPI is also out of │
│ service. Night departures at SFO with one parallel closed    │
│ appear in 3 ASRS reports describing runway/taxiway           │
│ misidentification at this airport.                           │
│   [notam:A1477/26] [asrs:1465123] [asrs:1502877]             │
└──────────────────────────────────────────────────────────────┘

┌ MED ─── WEATHER ─────────────────────────────── approach ───┐
│ KJFK TAF carries TEMPO 1/2SM +TSRA 0900Z–1200Z, inside your  │
│ arrival window. Forecast arrival delay for that hour is      │
│ 38 min (80% interval 12–94) against a 14 min baseline.       │
│   [taf:KJFK@0220Z] [forecast:jfk-0900Z]                      │
└──────────────────────────────────────────────────────────────┘

⊘ NOT DETERMINED — alternate minima at KBOS
  Approach-minimums source last updated 19 days ago and may be stale.
  No claim is made about alternate suitability.  [staleness:19d]
```

The abstention is deliberate. In a safety-adjacent system "I don't know" is a first-class output and
an evaluated behaviour, not a fallback.

Today the **deterministic core** produces the NOTAM and weather findings and the abstentions above,
with every claim cited, and no model in the loop. The precedent (ASRS) and delay-forecast rows are
Sprints 3 and 6; the agent layer in Sprint 4 enriches this core rather than replacing it.

---

## Status

Built in the open, six sprints over twelve weeks.

| Sprint | Focus | State |
|---|---|---|
| 1 | Foundation — schemas, rule decoder, ingestion, infra, deterministic briefing | 🟢 done (parser tuning waits on real NOTAM data) |
| 2 | Fine-tuned NOTAM entity extractor → HF Hub | ⬜ not started |
| 3 | Hybrid retrieval over ASRS/NTSB + reranking | ⬜ not started |
| 4 | LangGraph agent graph, grounding, abstention | ⬜ not started |
| 5 | Time-travel eval harness + CI regression gate | ⬜ not started |
| 6 | Delay forecasting, cost/latency, UI, MCP server | ⬜ not started |

**Working today:** ICAO Q-code taxonomy (145 subjects × 79 conditions), FAA/ICAO contraction
expansion, rule-based NOTAM parser producing typed records, strict briefing schemas, Postgres +
pgvector persistence with an "in force at this instant" query, METAR/TAF ingestion from
aviationweather.gov, a low-confidence escalation queue for the Sprint 2 extractor, a raw-payload
archive of every fetch, and a deterministic briefing (`preflight brief`, `POST /brief`) that turns
what's in the database into ranked, cited findings and explicit abstentions.

---

## Evaluation targets

No results yet — the harness lands in Sprint 5. These are the targets the CI gate will enforce, and
this table gets a `measured` column the moment there is something honest to put in it.

| Layer | Metric | Target | Measured |
|---|---|---:|---:|
| Extraction | macro entity F1 (RWY/TWY/NAVAID/OBST/AIRSPACE/TIME) | ≥ 0.92 | — |
| Retrieval | Recall@20 / nDCG@10 | ≥ 0.90 / 0.65 | — |
| Rerank | nDCG@10 lift over dense-only | +0.12 | — |
| Forecast | MASE vs seasonal-naive | < 0.85 | — |
| End-to-end | implicated-hazard recall (200 positives) | ≥ 0.85 | — |
| End-to-end | false-alarm rate (200 matched negatives) | < 0.15 | — |
| Grounding | claim-level citation accuracy | ≥ 0.97 | — |
| Abstention | correct abstention on data-gap cases | ≥ 0.90 | — |
| Safety | prompt-injection resistance (60 adversarial NOTAMs) | 100% | — |
| Judge | LLM-judge vs human agreement (Cohen's κ) | ≥ 0.70 | — |
| Cost | p50 $/briefing · p95 latency | < $0.08 · 25 s | — |

The κ row matters as much as the rest: an LLM judge nobody validated is a number nobody should trust.

---

## Architecture

```
 SOURCES              DECODE                STORE              REASON            VERIFY        SERVE
 ─────────            ──────                ─────              ──────            ──────        ─────
 FAA NOTAM      ┐                                        ┌ NotamAgent  ┐
 aviationweather├──▶ rules ──▶ ModernBERT ──▶ Postgres 16 ┼ WxAgent     ┤
 NASA ASRS      │    (Q-code    token clf     + pgvector  ┼ PrecedentAg ┼─▶ NLI      ──▶ FastAPI
 NTSB CAROL     │   + contract-  ↓ low conf   + tsvector  ┼ DelayAgent  ┤   entailment    SSE
 BTS on-time    │    ions)      LLM fallback   + Redis    ┼ ListenAgent ┤   + abstain     MCP
 OpenSky        ┘                                         └ supervisor  ┘   + injection   Next.js
                                                            (LangGraph)      filter
```

Six specialists run concurrently under a LangGraph supervisor with a Postgres checkpointer, so a
briefing survives a crash and latency is the slowest agent rather than the sum.

### Decisions worth arguing about

- **pgvector, not a dedicated vector DB.** One datastore gives transactional metadata filters
  alongside vectors. See [ADR 0001](docs/adr/0001-pgvector-over-dedicated-vector-db.md).
- **Hybrid retrieval, not dense-only.** Aviation queries are full of exact identifiers — `28R`,
  `KSFO`, `ILS 22L` — where embeddings alone fail. BM25 + dense, fused with RRF.
- **Rules before models before LLMs.** Q-codes and time windows are a solved problem in regex;
  spending a frontier model on them is a cost bug. The learned extractor handles the free-text `E)`
  field, and the LLM only sees what the first two layers flag as low-confidence.
- **Claims cannot exist without citations.** Enforced in the type system (`Claim.citations` has
  `min_length=1`), not by prompt instruction.

---

## Quickstart

```bash
git clone git@github.com:BhavyaPatel19/preflight.git
cd preflight

uv sync                     # creates .venv from the lockfile

pytest                      # decoder tests — no API keys, no network
cp .env.example .env        # fill in only what you need
```

Decode a NOTAM without any setup at all:

```bash
python -m preflight.decode.notam --demo
```

Infrastructure (Postgres + pgvector, Redis, MinIO, Langfuse) comes up with:

```bash
# Docker Desktop, or on macOS without it:  brew install colima docker docker-compose && colima start
make up                       # docker compose up -d — schema auto-applies on first boot
make db                       # apply db/*.sql migrations to an existing database

preflight dbcheck             # round-trips the database, confirms pgvector
preflight ingest weather KSFO KJFK
preflight ingest notams --file data/samples/notams-demo.txt
preflight brief KSFO KJFK --alt KBOS --off-block 2026-09-12T08:00Z --type A320
pytest                        # the db-marked tests now run instead of skipping
```

### Keeping the archive current

The time-travel evaluation replays what the system knew at a given instant, so the project keeps
its own history. `docker compose up -d scheduler` builds the app image and runs an hourly ingest
for the watchlist (default: the 30 busiest US airports; override with `PREFLIGHT_WATCHLIST`),
archiving every fetch under `data/raw/` and logging each run:

```
$ preflight status
notams   nasa-dip         2026-09-12 06:31Z  skipped  NASA DIP is not configured (...) — see docs/adr/0002.
weather  aviationweather  2026-09-12 06:31Z  ok       tafs=4 metars=7
```

The NOTAM job reports `skipped` until a source is configured, then starts filling the archive with
no code change. `preflight schedule` runs the same loop outside Docker.

---

## Repo layout

```
src/preflight/
  schemas.py            typed contracts — NotamRecord, Claim, Finding, Briefing
  decode/
    qcode.py            ICAO Q-code taxonomy (145 subjects × 79 conditions)
    contractions.py     FAA/ICAO contraction dictionary
    notam.py            rule-based parser: raw NOTAM → NotamRecord
  sources/              aviationweather client; NotamSource protocol + providers
  archive.py            raw-payload archive — every fetch, timestamped, before decode
  brief/                deterministic briefing core + text renderer
  db/                   plain-SQL persistence: notams, weather, pool
  ingest/               idempotent fetch → archive → decode → store jobs
  scheduler.py          hourly jobs + run log; `preflight schedule` / compose `scheduler`
  api/                  FastAPI service, SSE briefing endpoint
db/*.sql                Postgres schema + migrations (pgvector, full-text, HNSW)
docs/adr/               architecture decision records
tests/                  decoder tests against real NOTAM text
```

---

## Data sources

All public. Nothing in this repo is scraped.

> **On NOTAMs:** the FAA's NOTAM API is not open to the public, and its public search site refuses
> programmatic requests. The data is public domain; access to it is not. Ingestion is written against
> a provider interface so this doesn't leak into the rest of the system, and every fetch is archived
> raw so the project builds its own history for the time-travel evaluation. Details and what was
> tried: [ADR 0002](docs/adr/0002-notam-access-and-the-provider-abstraction.md).

| Source | Provides | Access |
|---|---|---|
| FAA NOTAMs via **NASA DIP** | live NOTAMs, structured from the FAA SWIM feed | request access — see [ADR 0002](docs/adr/0002-notam-access-and-the-provider-abstraction.md) |
| aviationweather.gov | METAR, TAF, PIREP, SIGMET, AIRMET | free, no key |
| NASA ASRS | ~200k de-identified incident narratives | free bulk export |
| NTSB CAROL | accident/incident records with findings | free export |
| BTS On-Time Performance | flight-level delay history | free bulk CSV |
| FAA NASR | airports, runways, navaids (gazetteer) | free, 28-day cycle |
| OpenSky Network | ADS-B traffic | free tier |

Corpora are **not** committed — `data/` is gitignored. `scripts/` will fetch them.

---

## License

MIT — see [LICENSE](LICENSE). The aeronautical data is the property of its respective publishers and
carries its own terms.
