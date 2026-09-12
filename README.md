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

![The briefing UI: a KSFO→KJFK flight with a runway closure, an ILS outage and a taxiway closure, each with cited NOTAMs and prior-report precedent](docs/briefing-ui.png)

`preflight serve` then open http://localhost:8000 — findings stream in as they resolve, every citation
clicks open to its source passage. For the runway closure at KSFO, the precedent search returned the
NTSB investigation of **Air Canada 759** — the incident this project is motivated by — with nothing tuned
for it.

The same briefing in the terminal, against the bundled sample NOTAMs and live weather. No model in the
loop; every claim carries a citation with a verbatim quote, and the schema makes an uncited claim
impossible.

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
evaluated behaviour.

With the retrieval models installed, each actionable finding also carries **precedent** from the
75,000-report corpus:

```
[HIGH] APPROACH AIDS KJFK: ILS 22L unserviceable (maintenance) until 11 Sep 1600Z (est)
       [notam:A0912/26]
       3 prior reports with no airport recorded describe similar conditions: “A319 flight crew
       reported a CFIT event during visual approach shortly after being assigned a late runway
       change. Flight crew utilized an INOP…”; …
       [asrs:1851101] [asrs:1223351] [asrs:1180257]
```

The query is the *operational consequence* of the NOTAM, not its wording — that framing is what
turned an irrelevant maintenance case into the report above — and the claim says plainly whether
the precedent happened at this airport or somewhere unrecorded. The delay forecast arrives in
Sprint 6; the Sprint 4 agent layer *enriches* this core rather than replacing it.

---

## Status

Built in the open, six sprints over twelve weeks.

| Sprint | Focus | State |
|---|---|---|
| 1 | Foundation — schemas, rule decoder, ingestion, archive, deterministic briefing, scheduler | 🟢 done |
| 2 | Fine-tuned NOTAM entity extractor → HF Hub | ⬜ waits on a real NOTAM corpus |
| 3 | Hybrid retrieval over ASRS/NTSB + reranking | 🟢 done — corpus, golden set, measured |
| 4 | LangGraph agent graph, grounding, abstention | ⬜ not started |
| 5 | Time-travel eval harness + CI regression gate | 🟡 600-case set built from NTSB (300 + 300 matched); scorer reports coverage honestly; judge + gate wait on an LLM key |
| 6 | Delay forecasting, cost/latency, UI, MCP server | 🟡 UI and MCP server done (pulled forward) |

**Working today**

- **Decode** — ICAO Q-code taxonomy (145 subjects × 79 conditions), FAA/ICAO contraction dictionary
  (263 terms), rule-based parser for ICAO and US-domestic NOTAMs producing typed records with
  clause-scoped entities and an honest `decode_confidence` for escalation routing.
- **Store** — Postgres 16 + pgvector; an "in force at this instant" query; a low-confidence
  escalation queue; every fetch archived raw before decode.
- **Ingest** — METAR/TAF from aviationweather.gov; NOTAMs through a provider interface (text dumps
  today, NASA DIP when access lands); hourly scheduler with a run log.
- **Brief** — `preflight brief` / `POST /brief` / `GET /brief/stream`: ranked, cited findings and
  explicit abstentions, with **precedent**: for each actionable finding, prior ASRS/NTSB reports
  describing what went wrong for crews in those conditions, each citing the verbatim passage.
- **UI** — `preflight serve` → http://localhost:8000: findings stream in over SSE, citations click
  open to the source passage, abstentions shown as their own block. URL parameters make a briefing
  shareable. One HTML file, no build step.
- **MCP** — `preflight mcp` exposes `brief`, `decode_notam`, `search_precedent` and `status` as
  Model Context Protocol tools over stdio, so Claude Desktop or Claude Code can call the system
  directly.
- **Retrieve** — hybrid search (pgvector + tsvector fused with RRF, cross-encoder reranked) over
  47,723 ASRS incident reports and 27,986 NTSB accident/incident investigations, with ablation
  switches for the eval.

---

## Evaluation targets

The retrieval rows are measured; the rest wait on their harnesses (Sprint 5). Targets are what the
CI gate will enforce.

| Layer | Metric | Target | Measured |
|---|---|---:|---:|
| Extraction | macro entity F1 (RWY/TWY/NAVAID/OBST/AIRSPACE/TIME) | ≥ 0.92 | — |
| Retrieval | Recall@20 / nDCG@10 — synopsis→narrative, 300 queries | ≥ 0.90 / 0.65 | 0.61 / 0.41 — [details](evals/retrieval/RESULTS.md) |
| Retrieval | P@10 on exact-identifier queries (`runway 28R` at an airport) | ≥ 0.80 | 0.77 |
| Rerank | nDCG@10 lift over dense-only | +0.12 | +0.09 |
| Forecast | MASE vs seasonal-naive | < 0.85 | — |
| End-to-end | implicated-hazard recall (300 NTSB positives) | ≥ 0.85 | — (0 / 300 covered: archive began 2026-09-11 — [details](evals/briefing/RESULTS.md)) |
| End-to-end | false-alarm rate (300 matched negatives) | < 0.15 | — (0 / 300 covered) |
| Grounding | claim-level citation accuracy | ≥ 0.97 | — |
| Abstention | correct abstention on data-gap cases | ≥ 0.90 | — |
| Safety | prompt-injection resistance (60 adversarial NOTAMs) | 100% | — |
| Judge | LLM-judge vs human agreement (Cohen's κ) | ≥ 0.70 | — |
| Cost | p50 $/briefing · p95 latency | < $0.08 · 25 s | — |

The κ row matters as much as the rest: an LLM judge nobody validated is a number nobody should trust.

The retrieval numbers are below target and that is the point of having them: the first run of the
harness found the lexical ranking function was both slow and bad, and fixing it moved hybrid from
*worse* than dense to better (`evals/retrieval/HISTORY.md`). Candidate-pool size is the next knob.

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

**The database** — two options. On a laptop, native is the right one: it idles at ~25 MB and
starts in a second, versus a 6 GB Linux VM for Docker.

```bash
# Option A — native Postgres (macOS)
brew install postgresql@17 pgvector
make db-start                       # pg_ctl on :5433; not a login service, nothing runs unless you start it
createdb -p 5433 preflight && psql -p 5433 preflight -c "CREATE ROLE preflight LOGIN PASSWORD 'preflight' SUPERUSER"
cp .env.example .env                # DATABASE_URL already points at :5433
make db                             # apply db/*.sql
make db-stop                        # when you're done

# Option B — the full Docker stack (what deploys): Postgres :5432, Redis, MinIO, Langfuse, scheduler
# Docker Desktop, or on macOS without it:  brew install colima docker docker-compose && colima start
make up                             # schema auto-applies on first boot; set DATABASE_URL to :5432
```

Then:

```bash
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
preflight corpus ingest ntsb --limit 500       # needs `brew install mdbtools`; downloads the 96 MB NTSB database
preflight corpus add --source ops_note --id note-1 --file note.txt --icao KSFO
preflight search "lined up with a taxiway instead of the runway at night"
preflight search "28R closed" --mode lexical --no-rerank      # ablation switches
preflight corpus stats
```

**MCP** — add to Claude Desktop's `claude_desktop_config.json` (or `claude mcp add` in Claude Code):

```json
{"mcpServers": {"preflight": {"command": "/ABSOLUTE/PATH/preflight/.venv/bin/preflight", "args": ["mcp"]}}}
```

Then ask: *"Brief KSFO to KJFK departing 0230Z tomorrow, alternate KBOS."* The models load on the
first call that needs them.

**API and UI** — `preflight serve`, then open http://localhost:8000. Endpoints: `POST /decode`,
`POST /brief`, `GET|POST /brief/stream` (SSE), `GET /health`. The retrieval models load once at
startup when the ML extras are installed; without them the briefing states that precedent was not
searched.

---

## Development

| Command | What |
|---|---|
| `make check` | lint (`ruff`), types (`mypy --strict`), tests — what CI runs |
| `pytest` | default: excludes `live` and `ml` |
| `pytest -m live` | hits real external APIs (aviationweather.gov) |
| `pytest -m ml` | loads the real embedding and reranker models |
| `preflight eval retrieval` | Recall/nDCG/P@10 per config on the 350-query golden set (~30 min) |
| `preflight eval briefing` | replay the briefing on 600 NTSB-derived cases; coverage, hazard recall, false alarms |
| `make db-start` / `make db-stop` | native Postgres on :5433 |
| `make up` / `make down` | the Docker stack on :5432 |
| `make demo` | decode the bundled NOTAMs |

CI runs on every push and PR against a `pgvector/pgvector:pg17` service container, applying
`db/*.sql` first, so the `db`-marked tests run for real there. On a laptop without Postgres they
skip. No model is ever downloaded in CI — retrieval tests use hash-based fakes behind the same
protocols.

Migrations are plain SQL in `db/`, applied in filename order; the Postgres container applies them
on first boot, `make db` applies them to an existing database.

Nothing starts on login. Native Postgres: `make db-start` when you sit down, `make db-stop` when
you're done. The Docker stack: `colima start && make up` (Colima stops on sleep and reboot).

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
    ntsb.py             NTSB avall.mdb via mdbtools: events + narratives + findings + sequence
  archive.py            raw-payload archive — every fetch, timestamped, before decode
  ingest/               idempotent fetch → archive → decode → store jobs; resumable corpus ingest
  scheduler.py          hourly jobs + run log; `preflight schedule` / compose `scheduler`
  db/                   plain-SQL persistence: notams, weather, corpus (hybrid search), runs, pool
  brief/                deterministic briefing core, precedent attachment, text renderer
  retrieval/            chunker, Embedder/Reranker protocols, Retriever (hybrid + rerank)
  evals/retrieval.py    golden-set builder, metrics, runner → evals/retrieval/RESULTS.md
  evals/briefing.py     NTSB-derived cases (positives + matched negatives), time-travel scorer
  api/                  FastAPI: /decode, /brief, /brief/stream, and static/index.html (the UI)
  mcp_server.py         the same capabilities as MCP tools over stdio (`preflight mcp`)
  cli.py                the `preflight` command
db/*.sql                schema + migrations (pgvector, full-text, HNSW)
docs/adr/               architecture decision records
evals/retrieval/        golden.jsonl (350 queries), RESULTS.md (latest run), HISTORY.md (what each run changed)
evals/briefing/         golden.jsonl (600 cases), RESULTS.md — coverage, recall, false alarms
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
| NTSB aviation database | 27,986 investigations 2008→ with date, nearest airport, weather, light, phase and cause-flagged findings — the golden-set raw material | free bulk download (`avall.zip`) |
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
