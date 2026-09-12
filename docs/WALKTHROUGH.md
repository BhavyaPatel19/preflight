# Walkthrough

How to demo Preflight in three minutes, and what to say about each number in the README table.
Everything here is reproducible from the repo; nothing is a slide.

## Setup (once, ~2 min after the corpus exists)

```bash
make db-start && preflight serve          # models load on first request, ~30 s
open http://localhost:8000
```

## The three-minute demo

**1. A briefing (45 s).** Enter `KSFO → KJFK`, alternate `KBOS`, an off-block a few hours out,
click *Brief*. Findings stream in ranked by severity. Point at three things:

- A NOTAM finding — *Runway 28R closed (work in progress) until …* — and click its citation. The
  raw NOTAM appears, with its validity window. "Every sentence traces to a record."
- The precedent claim under it, and click an `asrs:` citation. A real crew's narrative appears.
  "That's a NASA incident report. The system searched 75,000 of them for this situation."
- An abstention — *Not determined — KJFK forecast* — "and when it doesn't know, it says so.
  That's an evaluated behaviour, not an error path."

**2. The moment (30 s).** Run the bundled sample: `preflight brief KSFO KJFK --alt KBOS
--off-block 2026-09-11T02:30Z`. For the runway closure at KSFO, the precedent search returns the
NTSB investigation of **Air Canada 759** — the 2017 near-miss the README opens with. Nothing was
tuned for it; the scenario query ("runway closed, crew used the parallel, lined up with the wrong
runway or a taxiway") matched the report.

**3. The evals (90 s).** Open the README table. Four rows are measured. Tell the story of one:

> The retrieval harness's first run showed that fusing the lexical channel made results *worse*
> than dense-only. The cause was the ranking function — cover-density ranking over 81k OR-matches
> was slow and bad. One change, measured before and after: lexical nDCG@10 0.105 → 0.294, hybrid
> from worse-than-dense to better, latency down 8×. Then the identifier queries showed the ICAO
> code lives in metadata, not text. It's all in `evals/retrieval/HISTORY.md`.

## What each measured row means, and its honest limit

| Row | What was measured | What it does not claim |
|---|---|---|
| **Retrieval** nDCG@10 0.405 · Recall@20 0.607 | Paraphrase-to-passage: an ASRS analyst's synopsis finds the narrative it summarises, synopsis chunks hidden. 300 queries, objective labels. | Not judged precedent relevance for briefing-style queries. Below target; the ceiling is the embedder (candidate-pool experiment ruled out the pool). |
| **Identifier** P@10 0.772 | `runway 28R` with the airport as a metadata filter. Dense-only gets 0.54 — the exact-identifier weakness hybrid exists to cover, with a number on it. | 50 queries. |
| **Forecast** MASE 0.715 | Chronos-Bolt zero-shot vs seasonal-naive (1.067) and climatology (0.751) on a rolling-origin backtest, 406 forecasts across 29 airports. | The briefing cites climatology, not the model — BTS lands ~3 months late and a flight next week is beyond any honest horizon. |
| **Grounding** 1.000 / 1.000 | NLI verifier accepts every true claim and rejects every materially corrupted one (74 + 74) at threshold 0.5. | Deterministic core's own phrasing only. LLM prose is what this harness will gate. Building it forced citations to carry the evidence (validity windows, decoded METAR fields). |
| **Safety** 1.000 / 0.000 | Injection detector recall on 60 adversarial NOTAMs; false positives on benign. | Rules were iterated against the same set — an upper bound until a held-out set exists. LLM resistance itself is unmeasured until the agent layer exists. |
| **End-to-end** — | 600 NTSB-derived cases exist (300 positives with an investigated, briefable hazard; 300 matched negatives). Coverage 0/600. | The raw archive began 2026-09-11. Recall and false-alarm rate become real as new events land inside the archive or docket exhibits are reconstructed. The harness reports coverage rather than inventing a number. |

## Questions you will be asked

**"Why no LLM in the briefing?"** There is a deterministic floor — findings from records, cited,
with abstentions on gaps — and the agent layer *enriches* it: prose, precedent query rewriting,
synthesis. The verifier and the injection set were built first so the LLM layer is gated the day
it arrives. Every claim it writes still has to trace to a record.

**"Why pgvector, not Pinecone?"** Every retrieval query is a *filtered* similarity search — this
airport, this window — and the filter is the question. One statement fuses dense and lexical
candidates under the same filter. ADR 0001.

**"What broke?"** The lexical ranker (run 1). The timezone rendering bug the native-Postgres
switch exposed. A test that deleted the demo NOTAMs on every run. The NLI model reading `CLSD` as
a contradiction of "closed". Each one is in a commit message with the fix and the test.

**"What would you do next?"** Swap the embedder (`bge-large` / `bge-m3`) and re-run the retrieval
harness — Recall@20 is the number to watch. Then the agent layer, gated by the grounding and
injection harnesses that already exist.

## Honest scope

Research and portfolio system. Not certified, not validated, not for operational use. The NOTAM
feed is closed to the public (ADR 0002); the pipeline runs on dumps and its own archive until NASA
DIP access lands.
