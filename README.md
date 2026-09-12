# Preflight

**An agentic route-risk briefing system for flight operations — every claim cited, every capability measured, and explicit about what it doesn't know.**

Give it a flight. It reads every NOTAM, weather product and relevant historical incident for that
route, and returns a ranked hazard briefing where each sentence traces back to a source record.

```
$ preflight brief KSFO KJFK --alt KBOS --off-block 2026-09-11T02:30Z --type A320
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

Pair those positive cases with **matched negative controls** — uneventful flights matched on airport,
hour and season — and you can measure recall and false-alarm rate on the same footing. Alert fatigue
is the real failure mode of every safety system ever fielded, so precision is not a secondary metric.

One constraint shapes how that set gets built: nobody hands out historical NOTAMs (see
[ADR 0002](docs/adr/0002-notam-access-and-the-provider-abstraction.md)). So every fetch is archived
raw from day one, negatives come from that archive going forward, and positives older than the
archive come from NTSB docket exhibits, which include the NOTAMs in effect at the time.

This eval design is the centre of the project. Everything else is in service of it.

---

## What it does today

Real output from the deterministic core, against the bundled sample NOTAMs and live weather. No model
in the loop yet; every claim carries a citation with a verbatim quote, and the schema makes an uncited
claim impossible.

```
KSFO → KJFK (alt KBOS)  ·  A320  ·  off-block 11 Sep 0230Z
6 findings · 2 abstentions
──────────────────────────────────────────────────────────
[HIGH] RUNWAY        KSFO: Runway 28R closed (work in progress) until 11 Sep 0700Z
       takeoff, taxi
       KSFO — Runway 28R closed (work in progress) until 11 Sep 0700Z.
       [notam:A1477/26]

[HIGH] APPROACH AIDS KJFK: ILS 22L unserviceable (maintenance) until 11 Sep 1600Z (est)
       approach
       [notam:A0912/26]

[MED ] TAXIWAY       KSFO: Taxiway A closed between B and C until 11 Sep 0700Z (est)
       taxi
       [notam:!SFO 09/142]

[INFO] WEATHER       KSFO: VFR — wind 300/7 kt, vis 10 SM
       taxi, takeoff, climb
       [metar:KSFO@120600Z]
…
[ ⊘  ] NOT DETERMINED  KJFK forecast
       No TAF for KJFK covers 11 Sep 0300Z–11 Sep 1030Z.  [no_coverage]

sources considered: 9 · 19 ms
```

Those two abstentions are correct, not a bug: the flight was yesterday and the only TAFs on record
were issued today. In a safety-adjacent system "I don't know" is a first-class output and an
evaluated behaviour. The precedent (ASRS) and delay-forecast findings arrive in Sprints 3 and 6; the
Sprint 4 agent layer *enriches* this core rather than replacing it.

---

## Status

Built in the open, six sprints over twelve weeks.

| Sprint | Focus | State |
|---|---|---|
| 1 | Foundation — schemas, rule decoder, ingestion, archive, deterministic briefing, scheduler | 🟢 done |
| 2 | Fine-tuned NOTAM entity extractor → HF Hub | ⬜ waits on a real NOTAM corpus |
| 3 | Hybrid retrieval over ASRS/NTSB + reranking | 🟡 retrieval core + ASRS corpus (47.7k reports) done; NTSB and golden set next |
| 4 | LangGraph agent graph, grounding, abstention | ⬜ not started |
| 5 | Time-travel eval harness + CI regression gate | ⬜ not started |
| 6 | Delay forecasting, cost/latency, UI, MCP server | ⬜ not started |

**Working today**

- **Decode** — ICAO Q-code taxonomy (145 subjects × 79 conditions), FAA/ICAO contraction dictionary
  (263 terms), rule-based parser for ICAO and US-domestic NOTAMs producing typed records with
  clause-scoped entities and an honest `decode_confidence` for escalation routing.
- **Store** — Postgres 16 + pgvector; an "in force at this instant" query; a low-confidence
  escalation queue; every fetch archived raw before decode.
- **Ingest** — METAR/TAF from aviationweather.gov; NOTAMs through a provider interface (text dumps
  today, NASA DIP when access lands); hourly scheduler with a run log.
- **Brief** — `preflight brief` / `POST /brief` / `POST /brief/stream`: ranked, cited findings and
  explicit abstentions.
- **Retrieve** — hybrid search (pgvector + tsvector fused with RRF, cross-encoder reranked) over
  47,723 real ASRS incident reports, with ablation switches for the eval.

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
| End-to-end | implicated-hazard recall (positives) | ≥ 0.85 | — |
| End-to-end | false-alarm rate (matched negatives) | < 0.15 | — |
| Grounding | claim-level citation accuracy | ≥ 0.97 | — |
| Abstention | correct abstention on data-gap cases | ≥ 0.90 | — |
| Safety | prompt-injection resistance (60 adversarial NOTAMs) | 100% | — |
| Judge | LLM-judge vs human agreement (Cohen's κ) | ≥ 0.70 | — |
| Cost | p50 $/briefing · p95 latency | < $0.08 · 25 s | — |

The κ row matters as much as the rest: an LLM judge nobody validated is a number nobody should trust.

---

## Architecture

```
 SOURCES               DECODE                 STORE                 REASON               VERIFY        SERVE
 ───────               ──────                 ─────                 ──────               ──────        ─────
 NASA DIP / dumps ┐                                             ┌ deterministic core ┐
 aviationweather  ├─▶ archive ─▶ rules ─▶ ModernBERT ─▶ Postgres ┤   (today)          ├─▶ NLI      ─▶ FastAPI
 NASA ASRS        │    raw       Q-code    token clf    pgvector  ┤ NotamAgent          │   entailment    SSE
 NTSB CAROL       │             + contr-   ↓ low conf   tsvector  ┤ WxAgent   Precedent┤   + abstain     MCP
 BTS on-time      ┘             actions    LLM fallback + Redis   ┤ DelayAgent Listen  │   + injection   Next.js
                                                                  └ supervisor (S4)   ┘   filter
```

The deterministic core (Sprint 1) is the floor: cited findings from records, abstentions on gaps.
Sprint 4's LangGraph supervisor fans out to specialists that add precedent, forecasts and prose on
top of it — every claim they make still has to trace to a record, and the verifier drops the ones
that don't.

### Decisions worth arguing about

- **pgvector, not a dedicated vector DB.** Every retrieval query is a *filtered* similarity search
  — this airport, this window — and the filter is the question, not an optimisation.
  [ADR 0001](docs/adr/0001-pgvector-over-dedicated-vector-db.md)
- **A provider interface for NOTAMs, and archive everything.** The FAA's API is closed to the public;
  the data is public domain. Ingestion is written against a protocol, and every fetch is written to
  disk before decode so the project builds its own history.
  [ADR 0002](docs/adr/0002-notam-access-and-the-provider-abstraction.md)
- **Hybrid retrieval, reranked, with dev-speed models by default.** Aviation queries are full of
  exact identifiers (`28R`, `ILS 22L`) that embeddings blur; narrative queries are the reverse. Both
  channels, fused in SQL. `bge-m3` is the *measured* upgrade path, not the default.
  [ADR 0003](docs/adr/0003-hybrid-retrieval.md)
- **Rules before models before LLMs.** Q-codes and time windows are a solved problem in regex;
  spending a frontier model on them is a cost bug. The learned extractor handles the free-text `E)`
  field; the LLM only sees what the first two layers flag as low-confidence.
- **Claims cannot exist without citations.** Enforced in the type system (`Claim.citations` has
  `min_length=1`), not by prompt instruction.

---

## Quickstart

```bash
git clone git@github.com:BhavyaPatel19/preflight.git && cd preflight
uv sync                             # .venv from the lockfile
pytest                              # 128 tests, no keys, no network; db-marked tests skip without Postgres

python -m preflight.decode.notam --demo     # decode three NOTAMs with zero setup
```

**The stack** — Postgres + pgvector, Redis, MinIO, Langfuse, and the ingest scheduler:

```bash
# Docker Desktop, or on macOS without it:  brew install colima docker docker-compose && colima start
cp .env.example .env                # fill in only what you need
make up                             # docker compose up -d; schema auto-applies on first boot
make db                             # apply db/*.sql to an existing database

preflight dbcheck                   # round-trips the database, confirms pgvector
preflight ingest weather KSFO KJFK
preflight ingest notams --file data/samples/notams-demo.txt
preflight brief KSFO KJFK --alt KBOS --off-block 2026-09-12T14:00Z --type A320
preflight status                    # last ingest run per source
```

**Retrieval** — needs the ML extras (~1.5 GB of model weights land in the Hugging Face cache on
first use):

```bash
uv sync --extra ml
preflight corpus ingest asrs --limit 2000      # ~20 reports/s on Apple Silicon; drop --limit for all 47.7k
preflight corpus add --source ops_note --id note-1 --file note.txt --icao KSFO
preflight search "lined up with a taxiway instead of the runway at night"
preflight search "28R closed" --mode lexical --no-rerank      # ablation switches
preflight corpus stats
```

**API** — `preflight serve`, then `POST /decode`, `POST /brief`, `POST /brief/stream` (SSE), `GET /health`.

---

## Development

| Command | What |
|---|---|
| `make check` | lint (`ruff`), types (`mypy --strict`), tests — what CI runs |
| `pytest` | default: excludes `live` and `ml` |
| `pytest -m live` | hits real external APIs (aviationweather.gov) |
| `pytest -m ml` | loads the real embedding and reranker models |
| `make up` / `make down` | the compose stack |
| `make demo` | decode the bundled NOTAMs |

CI runs on every push and PR against a `pgvector/pgvector:pg16` service container, applying
`db/*.sql` first, so the `db`-marked tests run for real there. On a laptop without Postgres they
skip. No model is ever downloaded in CI — retrieval tests use hash-based fakes behind the same
protocols.

Migrations are plain SQL in `db/`, applied in filename order; the Postgres container applies them
on first boot, `make db` applies them to an existing database.

After a reboot (Colima stops on sleep): `colima start && docker compose up -d`.

---

## Repo layout

```
src/preflight/
  schemas.py            typed contracts — NotamRecord, Claim, Finding, Abstention, Briefing
  decode/
    qcode.py            ICAO Q-code taxonomy (145 subjects × 79 conditions)
    contractions.py     FAA/ICAO contraction dictionary (263 terms)
    notam.py            rule-based parser: raw NOTAM → NotamRecord
  sources/
    aviationweather.py  METAR/TAF client
    notams.py           NotamSource protocol; FileSource, NasaDipSource
    asrs.py             ASRS export download + row parsing (locale→ICAO, phase taxonomy)
  archive.py            raw-payload archive — every fetch, timestamped, before decode
  ingest/               idempotent fetch → archive → decode → store jobs; resumable corpus ingest
  scheduler.py          hourly jobs + run log; `preflight schedule` / compose `scheduler`
  db/                   plain-SQL persistence: notams, weather, corpus (hybrid search), runs, pool
  brief/                deterministic briefing core + text renderer
  retrieval/            chunker, Embedder/Reranker protocols, Retriever (hybrid + rerank)
  api/                  FastAPI: /decode, /brief, /brief/stream
  cli.py                the `preflight` command
db/*.sql                schema + migrations (pgvector, full-text, HNSW)
docs/adr/               architecture decision records
tests/                  129 tests; markers: db, live, ml
data/samples/           bundled sample NOTAMs (real corpora are gitignored under data/raw)
```

---

## Data sources

All public. Nothing in this repo is scraped.

| Source | Provides | Access |
|---|---|---|
| FAA NOTAMs via **NASA DIP** | live NOTAMs, structured from the FAA SWIM feed | request access — [ADR 0002](docs/adr/0002-notam-access-and-the-provider-abstraction.md) |
| aviationweather.gov | METAR, TAF, PIREP, SIGMET, AIRMET | free, no key |
| NASA ASRS | 47,723 de-identified incident reports with the full ASRS taxonomy, via [`elihoole/asrs-aviation-reports`](https://huggingface.co/datasets/elihoole/asrs-aviation-reports) | HF Hub, Apache-2.0 packaging over public-domain data |
| NTSB CAROL | accident/incident records with findings — golden-set labels | free export |
| BTS On-Time Performance | flight-level delay history | free bulk CSV |
| FAA NASR | airports, runways, navaids (gazetteer) | free, 28-day cycle |
| OpenSky Network | ADS-B traffic | free tier |

> **On NOTAMs:** the FAA's NOTAM API is not open to the public, and its public search site refuses
> programmatic requests. The data is public domain; access to it is not. Ingestion is written against
> a provider interface so this doesn't leak into the rest of the system, and every fetch is archived
> raw so the project builds its own history for the time-travel evaluation.

---

## Design records

| ADR | Decision |
|---|---|
| [0001](docs/adr/0001-pgvector-over-dedicated-vector-db.md) | pgvector in Postgres, not a dedicated vector database |
| [0002](docs/adr/0002-notam-access-and-the-provider-abstraction.md) | NOTAM access is gated; provider interface, archive forward, NTSB-docket positives |
| [0003](docs/adr/0003-hybrid-retrieval.md) | Hybrid retrieval in Postgres, reranked; dev-speed models by default |

---

## License

MIT — see [LICENSE](LICENSE). The aeronautical data is the property of its respective publishers and
carries its own terms.
