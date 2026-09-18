"""``preflight`` command line."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from preflight import __version__
from preflight.decode.notam import DEMO_NOTAMS, NotamParseError, parse_notam


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="preflight", description="Route-risk briefing tools.")
    ap.add_argument("--version", action="version", version=f"preflight {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("decode", help="decode a NOTAM to JSON")
    d.add_argument("text", nargs="?", help="raw NOTAM text (reads stdin if omitted)")

    sub.add_parser("demo", help="decode the bundled example NOTAMs")

    s = sub.add_parser("serve", help="run the HTTP API")
    s.add_argument("--port", type=int, default=8000)

    i = sub.add_parser("ingest", help="fetch, decode and store")
    isub = i.add_subparsers(dest="source", required=True)
    w = isub.add_parser("weather", help="METAR/TAF from aviationweather.gov")
    w.add_argument("icao", nargs="+", help="airports, e.g. KSFO KJFK")
    w.add_argument("--hours", type=int, default=3)
    dl = isub.add_parser("delays", help="BTS on-time performance → hourly arrival delays")
    dl.add_argument("--months", type=int, default=12)
    dl.add_argument("--latest", help="YYYY-MM of the newest month (default: 3 months ago)")
    n = isub.add_parser("notams", help="NOTAMs from a dump file or a provider")
    n.add_argument("--file", type=Path, action="append", help="text dump; repeatable")
    n.add_argument("--source", choices=["nasa-dip"], help="live provider (needs credentials)")
    n.add_argument("icao", nargs="*", help="airports for a live provider")

    sub.add_parser("dbcheck", help="round-trip the database")

    ev = sub.add_parser("eval", help="evaluation harnesses")
    evsub = ev.add_subparsers(dest="suite", required=True)
    er = evsub.add_parser("retrieval", help="Recall/nDCG per retrieval config on the golden set")
    er.add_argument("--build", action="store_true", help="(re)build evals/retrieval/golden.jsonl")
    er.add_argument("--limit", type=int, help="only the first N queries (quick check)")
    er.add_argument("--no-rerank", action="store_true", help="skip the reranker config")
    er.add_argument("--candidates", type=int, default=40)
    er.add_argument("--kind", choices=["synopsis", "identifier"], help="run only one query set")
    er.add_argument("--config", action="append", metavar="NAME",
                    help="only these configs (repeatable), e.g. --config hybrid+rerank")
    er.add_argument("--rewrite", action="store_true",
                    help="add the hybrid+rerank+rewrite config: synopsis queries rewritten by "
                         "the configured LLM first (cached per model)")
    ee = evsub.add_parser("embedder", help="embedder ablation on a corpus subset, in memory")
    ee.add_argument("--models", nargs="+", help="sentence-transformers ids (first = baseline)")
    ee.add_argument("--size", type=int, default=40_000, help="subset size in chunks")
    ee.add_argument("--limit", type=int, help="only the first N synopsis queries (quick check)")
    ef = evsub.add_parser("forecast", help="Chronos-Bolt vs seasonal-naive vs climatology backtest")
    ef.add_argument("--days", type=int, default=14)
    ef.add_argument("--airports", nargs="*")
    evsub.add_parser("grounding", help="NLI verifier: accept true claims, reject corrupted ones")
    evsub.add_parser("safety", help="injection red-team set: detector recall, false positives")
    evsub.add_parser("abstention", help="constructed data-gap cases: does the briefing abstain?")
    ex_ev = evsub.add_parser("extraction", help="entity P/R/F1 of the rule decoder (and the model) "
                                                "on the hand-labelled gold set")
    ex_ev.add_argument("--model", type=Path, help="fine-tuned extractor directory")
    eg = evsub.add_parser("gate", help="regression gate: committed summaries vs evals/gates.toml")
    eg.add_argument("--live", action="store_true",
                    help="re-run the model-free suites (safety, abstention) first")
    eg.add_argument("--backfill", nargs="*", metavar="SUITE",
                    help="write summary.json from the newest run file of these suites")
    evsub.add_parser("narrative", help="unsupported-claim rate of the configured LLM's prose")
    ep = evsub.add_parser("precedent", help="LLM judge on (hazard, prior report) pairs + sheet")
    ep.add_argument("--build", action="store_true", help="rebuild pairs.jsonl and the sheet")
    ep.add_argument("--score", action="store_true", help="score the filled labels.csv (κ)")
    ep.add_argument("--limit", type=int, help="judge only the first N pairs")
    eb = evsub.add_parser("briefing", help="time-travel briefing eval on NTSB-derived cases")
    eb.add_argument("--build", action="store_true", help="(re)build evals/briefing/golden.jsonl")
    eb.add_argument("--limit", type=int)
    eb.add_argument("--backfill-weather", action="store_true",
                    help="first pull each weather case's historical METARs from the Iowa State "
                         "ASOS archive (public, no account) into the weather table")

    ex = sub.add_parser("extract", help="NOTAM entity extractor: data, training, inference")
    exsub = ex.add_subparsers(dest="op", required=True)
    xs = exsub.add_parser("synth", help="write synthetic train/val NOTAM bodies with BIO tags")
    xs.add_argument("--n", type=int, default=8000)
    xs.add_argument("--seed", type=int, default=20260918)
    exsub.add_parser("gold", help="rebuild evals/extraction/gold.jsonl from the labelled sources")

    sc = sub.add_parser("schedule", help="run the ingest scheduler (hourly weather + NOTAMs)")
    sc.add_argument("--no-run-now", action="store_true", help="wait for the first tick")

    sub.add_parser("status", help="last ingest run per source")

    sub.add_parser("mcp", help="serve briefing, decoder and precedent search as MCP tools (stdio)")

    co = sub.add_parser("corpus", help="precedent corpus")
    cosub = co.add_subparsers(dest="op", required=True)
    ca = cosub.add_parser("add", help="chunk, embed and index one document")
    ca.add_argument("--source", required=True, choices=["asrs", "ntsb", "far_aim", "ops_note"])
    ca.add_argument("--id", required=True, help="external id, e.g. ASRS ACN")
    ca.add_argument("--file", type=Path, required=True)
    ca.add_argument("--title")
    ca.add_argument("--icao")
    cosub.add_parser("stats", help="document and chunk counts")
    cr = cosub.add_parser("reembed", help="re-embed every chunk with the configured model "
                                          "(resumable; drop the index first — migration 007)")
    cr.add_argument("--model", help="sentence-transformers id (default: settings)")
    cr.add_argument("--batch", type=int, default=128)
    cr.add_argument("--source", choices=["asrs", "ntsb", "far_aim", "ops_note"],
                    help="only this document source")
    cx = cosub.add_parser("reindex", help="rebuild the corpus HNSW index over the loaded table")
    cx.add_argument("--m", type=int, default=16)
    cx.add_argument("--ef-construction", type=int, default=128)
    ci = cosub.add_parser("ingest", help="download, chunk, embed and index a corpus")
    ci.add_argument("corpus", choices=["asrs", "ntsb"])
    ci.add_argument("--limit", type=int, help="stop after N reports (for a first pass)")
    ci.add_argument("--split", action="append", choices=["train", "validation", "test"],
                    help="ASRS split(s); default all")

    se = sub.add_parser("search", help="hybrid search over the corpus")
    se.add_argument("query")
    se.add_argument("-k", type=int, default=5)
    se.add_argument("--icao")
    se.add_argument("--mode", choices=["hybrid", "dense", "lexical"], default="hybrid")
    se.add_argument("--no-rerank", action="store_true")

    b = sub.add_parser("brief", help="build a briefing from what is in the database")
    b.add_argument("departure")
    b.add_argument("destination")
    b.add_argument("--alt", action="append", default=[], help="alternate; repeatable")
    b.add_argument("--off-block", required=True, help="ISO-8601 UTC, e.g. 2026-09-11T02:30Z")
    b.add_argument("--type", dest="aircraft_type", help="e.g. A320")
    b.add_argument("--ete", type=int, help="estimated time en route, minutes (default 180)")
    b.add_argument("--json", action="store_true", help="emit JSON instead of text")
    b.add_argument("--no-precedent", action="store_true",
                   help="skip the prior-report search (faster; no model load)")
    b.add_argument("--verify", action="store_true",
                   help="run the NLI grounding verifier over every factual claim")
    b.add_argument("--resume", metavar="ID", help="resume/reload a checkpointed briefing by id")
    b.add_argument("--llm", action="store_true",
                   help="use the configured model for precedent queries and narrative "
                        "(implies --verify; unsupported sentences are dropped)")

    bn = sub.add_parser("bench", help="p50/p95 latency per briefing stage over repeated runs")
    bn.add_argument("departure")
    bn.add_argument("destination")
    bn.add_argument("--off-block", required=True, help="ISO-8601 UTC")
    bn.add_argument("--runs", type=int, default=3)
    bn.add_argument("--no-warmup", action="store_true", help="count the first run too")
    bn.add_argument("--no-precedent", action="store_true")
    bn.add_argument("--llm", action="store_true", help="include rewrite + narrative")
    bn.add_argument("--label", default="", help="heading for the markdown table")

    args = ap.parse_args(argv)

    if args.cmd == "decode":
        text = args.text or sys.stdin.read()
        try:
            print(parse_notam(text).model_dump_json(indent=2))
        except NotamParseError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        return 0

    if args.cmd == "demo":
        for raw in DEMO_NOTAMS:
            print(parse_notam(raw).model_dump_json(indent=2))
        return 0

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("preflight.api.main:app", port=args.port, reload=True)
        return 0

    if args.cmd == "ingest":
        from preflight.db import close_pool

        try:
            if args.source == "weather":
                import asyncio

                from preflight.ingest.weather import ingest_weather

                print(asyncio.run(ingest_weather(args.icao, hours=args.hours)))
            elif args.source == "delays":
                from preflight.ingest.delays import ingest_delays

                latest = tuple(int(x) for x in args.latest.split("-")) if args.latest else None
                print(ingest_delays(months=args.months, latest=latest))  # type: ignore[arg-type]
            else:
                import asyncio

                from preflight.ingest.notams import ingest_notams
                from preflight.sources.notams import (
                    FileSource,
                    NasaDipSource,
                    NotamSource,
                    SourceUnavailable,
                )

                notam_src: NotamSource
                if args.file:
                    notam_src = FileSource(*args.file)
                elif args.source == "nasa-dip":
                    from preflight.config import settings

                    cfg = settings()
                    notam_src = NasaDipSource(cfg.nasa_dip_base_url, cfg.nasa_dip_token)
                else:
                    print("error: give --file PATH or --source nasa-dip ICAO...", file=sys.stderr)
                    return 2
                try:
                    print(asyncio.run(ingest_notams(notam_src, args.icao)))
                except SourceUnavailable as e:
                    print(f"source unavailable: {e}", file=sys.stderr)
                    return 3
        finally:
            close_pool()
        return 0

    if args.cmd == "brief":
        from datetime import datetime

        from preflight.brief import load_retriever, render_text
        from preflight.config import settings
        from preflight.db import close_pool, get_pool
        from preflight.graph import (
            Deps,
            build_graph,
            pooled_connect,
            postgres_checkpointer,
            run_briefing,
        )
        from preflight.schemas import FlightRequest

        req = FlightRequest(
            departure=args.departure.upper(), destination=args.destination.upper(),
            alternates=tuple(a.upper() for a in args.alt),
            off_block=datetime.fromisoformat(args.off_block.replace("Z", "+00:00")),
            aircraft_type=args.aircraft_type, ete_minutes=args.ete,
        )
        llm = None
        if args.llm:
            from preflight.llm import load_llm

            llm = load_llm()
            if llm is None:
                print("warning: no LLM available (is `ollama serve` running?); "
                      "continuing without narrative", file=sys.stderr)
        verifier = None
        if args.verify or llm is not None:
            from preflight.verify.ground import load_verifier

            verifier = load_verifier()
        deps = Deps(connect=pooled_connect(get_pool),
                    retriever=None if args.no_precedent else load_retriever(),
                    verifier=verifier, llm=llm)
        try:
            with postgres_checkpointer(settings().database_url) as saver:
                graph = build_graph(deps, saver)
                briefing, state = run_briefing(
                    graph, req, options={"precedent": not args.no_precedent,
                                         "verify": bool(args.verify or llm),
                                         "narrative": llm is not None},
                    thread_id=args.resume,
                )
        finally:
            close_pool()
        for line in state.get("trace", []):
            print(f"· {line}", file=sys.stderr)
        print(f"· briefing id {briefing.trace_id}", file=sys.stderr)
        print(briefing.model_dump_json(indent=2) if args.json else render_text(briefing))
        return 0

    if args.cmd == "bench":
        from datetime import datetime

        from preflight.brief import load_retriever
        from preflight.db import close_pool, get_pool
        from preflight.evals.latency import bench, render_markdown
        from preflight.graph import Deps, Options, build_graph, pooled_connect
        from preflight.schemas import FlightRequest

        req = FlightRequest(
            departure=args.departure.upper(), destination=args.destination.upper(),
            off_block=datetime.fromisoformat(args.off_block.replace("Z", "+00:00")),
        )
        llm = verifier = None
        if args.llm:
            from preflight.llm import load_llm
            from preflight.verify.ground import load_verifier

            llm, verifier = load_llm(), load_verifier()
            if llm is None:
                print("error: no LLM available (is `ollama serve` running?)", file=sys.stderr)
                return 3
        deps = Deps(connect=pooled_connect(get_pool),
                    retriever=None if args.no_precedent else load_retriever(),
                    verifier=verifier, llm=llm)
        options: Options = {"precedent": not args.no_precedent, "verify": llm is not None,
                            "narrative": llm is not None}
        try:
            bres = bench(build_graph(deps), req, options=options, runs=args.runs,
                         warmup=not args.no_warmup)
        finally:
            close_pool()
        print(render_markdown(bres, label=args.label))
        return 0

    if args.cmd == "schedule":
        import asyncio

        from preflight.db import close_pool
        from preflight.scheduler import run_forever

        try:
            asyncio.run(run_forever(run_now=not args.no_run_now))
        except KeyboardInterrupt:
            pass
        finally:
            close_pool()
        return 0

    if args.cmd == "status":
        from preflight.db import close_pool, get_pool
        from preflight.db.runs import last_runs

        try:
            with get_pool().connection() as conn:
                rows = last_runs(conn)
        finally:
            close_pool()
        if not rows:
            print("no ingest runs recorded yet")
        for r in rows:
            counts = " ".join(f"{k}={v}" for k, v in r.counts.items())
            tail = f"  {r.error}" if r.error else f"  {counts}"
            when = f"{r.finished_at:%Y-%m-%d %H:%M}Z"
            print(f"{r.kind:<8} {r.source:<16} {when}  {r.status:<7}{tail}")
        return 0

    if args.cmd == "corpus":
        from preflight.db import close_pool, get_pool

        if args.op == "ingest":
            from preflight.ingest.corpus import ingest_asrs, ingest_ntsb
            from preflight.retrieval.embed import STEmbedder

            try:
                if args.corpus == "ntsb":
                    print(ingest_ntsb(STEmbedder(), limit=args.limit))
                else:
                    print(ingest_asrs(STEmbedder(), limit=args.limit,
                                      splits=tuple(args.split) if args.split else
                                      ("train", "validation", "test")))
            finally:
                close_pool()
            return 0
        try:
            with get_pool().connection() as conn:
                if args.op == "stats":
                    from preflight.db.corpus import stats

                    print(stats(conn))
                elif args.op == "reembed":
                    from preflight.retrieval.embed import STEmbedder
                    from preflight.retrieval.search import reembed

                    emb = STEmbedder(args.model, batch_size=64)
                    n_done = reembed(conn, emb, batch=args.batch, source=args.source,
                                     log=lambda m: print(m, file=sys.stderr, flush=True))
                    print(f"re-embedded {n_done:,} chunks with {emb.name}")
                elif args.op == "reindex":
                    from preflight.retrieval.search import reindex

                    secs = reindex(conn, m=args.m, ef_construction=args.ef_construction)
                    print(f"chunks_embedding_idx rebuilt (m={args.m}, "
                          f"ef_construction={args.ef_construction}) in {secs / 60:.1f} min")
                else:
                    from preflight.retrieval.embed import STEmbedder
                    from preflight.retrieval.search import index_document

                    n_chunks = index_document(
                        conn, STEmbedder(), source=args.source, external_id=args.id,
                        text=args.file.read_text(), title=args.title,
                        icao=args.icao.upper() if args.icao else None,
                    )
                    conn.commit()
                    print(f"indexed {args.source}:{args.id} — {n_chunks} chunks")
        finally:
            close_pool()
        return 0

    if args.cmd == "search":
        from preflight.db import close_pool, get_pool
        from preflight.retrieval.embed import STEmbedder, STReranker
        from preflight.retrieval.search import Retriever

        retriever = Retriever(STEmbedder(), None if args.no_rerank else STReranker())
        try:
            with get_pool().connection() as conn:
                hits = retriever.search(
                    conn, args.query, k=args.k, mode=args.mode,
                    icao=args.icao.upper() if args.icao else None, rerank=not args.no_rerank,
                )
        finally:
            close_pool()
        for h in hits:
            rr = f" rerank={h.rerank_score:.3f}" if h.rerank_score is not None else ""
            ch = ("D" if h.in_dense else "-") + ("L" if h.in_lexical else "-")
            print(f"[{ch}] {h.ref:<28} fused={h.fused_score:.4f}{rr}")
            print(f"     {h.text[:160]}{'…' if len(h.text) > 160 else ''}")
        return 0

    if args.cmd == "eval" and args.suite == "precedent":
        from preflight.db import close_pool, get_pool
        from preflight.evals import precedent as P
        from preflight.llm import load_llm

        llm = load_llm()
        try:
            if args.score:
                import json as _json

                pairs = P.load_pairs()
                verdicts = _json.loads((P.DIR / "verdicts.json").read_text())
                res = P.summarize(pairs, verdicts, P.read_sheet(),
                                  model=verdicts.get("_judge", "?"))
                P.RESULTS.write_text(P.to_markdown(res))
                print(P.to_markdown(res))
                return 0
            if llm is None:
                print("error: no LLM available (ollama serve?)", file=sys.stderr)
                return 3
            if args.build or not P.PAIRS.exists():
                from preflight.retrieval.embed import STEmbedder, STReranker
                from preflight.retrieval.search import Retriever

                with get_pool().connection() as conn:
                    pairs = P.build_pairs(conn, Retriever(STEmbedder(), STReranker()), llm)
                P.save_pairs(pairs)
                n_rows = P.write_sheet(pairs)
                print(f"pairs: {len(pairs)} → {P.PAIRS}; sheet: {n_rows} rows → {P.SHEET}")
            pairs = P.load_pairs()
            if args.limit:
                pairs = pairs[: args.limit]
            verdicts = P.judge_all(llm, pairs)
            verdicts["_judge"] = llm.name  # type: ignore[assignment]
            res = P.summarize(pairs, verdicts, P.read_sheet() if P.SHEET.exists() else {},
                              model=llm.name)
            run_path, md_path = P.save_run(res, verdicts)
            print(P.to_markdown(res))
            print(f"written: {run_path}  {md_path}")
        finally:
            close_pool()
        return 0

    if args.cmd == "eval" and args.suite == "narrative":
        from preflight.db import close_pool, get_pool
        from preflight.evals import narrative as N
        from preflight.llm import load_llm
        from preflight.verify.nli import HFVerifier

        llm = load_llm()
        if llm is None:
            print("error: no LLM available (PREFLIGHT_LLM / ollama serve)", file=sys.stderr)
            return 3
        try:
            with get_pool().connection() as conn:
                res = N.run(conn, llm, HFVerifier())
            run_path, md_path = N.save_run(res)
            print(N.to_markdown(res))
            print(f"written: {run_path}  {md_path}")
        finally:
            close_pool()
        return 0

    if args.cmd == "eval" and args.suite == "gate":
        from preflight.evals import gate

        if args.backfill:
            for p in gate.backfill(args.backfill):
                print(f"backfilled: {p}")
        if args.live:
            from preflight.db import close_pool, get_pool

            try:
                ran = gate.run_live(lambda: get_pool().connection())
            finally:
                close_pool()
            print(f"live: {', '.join(ran)}")
        outcomes = gate.evaluate(gate.load_gates())
        print(gate.to_markdown(outcomes))
        return 0 if gate.passed(outcomes) else 1

    if args.cmd == "extract":
        if args.op == "synth":
            from preflight.extract.synth import OUT, write_dataset

            sizes = write_dataset(args.n, seed=args.seed)
            print(f"synthetic NOTAMs → {OUT}: {sizes}")
            return 0
        if args.op == "gold":
            from preflight.extract.gold import GOLD, write

            print(f"gold set: {write()} bodies → {GOLD}")
            return 0

    if args.cmd == "eval" and args.suite == "extraction":
        from preflight.evals import extraction as X
        from preflight.extract.synth import OUT

        predictors: dict[str, X.Predictor] = {"rules": X.predict_rules}
        if args.model:
            from preflight.extract.model import load_predictor

            predictors["model"] = load_predictor(args.model)
        res = X.run(predictors, synthetic_val=OUT / "val.jsonl")
        run_path, md_path = X.save_run(res)
        print(X.to_markdown(res))
        print(f"written: {run_path}  {md_path}")
        return 0

    if args.cmd == "eval" and args.suite == "abstention":
        from preflight.db import close_pool, get_pool
        from preflight.evals import abstention as AB

        try:
            with get_pool().connection() as conn:
                res = AB.run(conn)
        finally:
            close_pool()
        run_path, md_path = AB.save_run(res)
        print(AB.to_markdown(res))
        print(f"written: {run_path}  {md_path}")
        return 0

    if args.cmd == "eval" and args.suite == "safety":
        from preflight.evals import safety as S

        res = S.run()
        run_path, md_path = S.save_run(res)
        print(S.to_markdown(res))
        print(f"written: {run_path}  {md_path}")
        return 0

    if args.cmd == "eval" and args.suite == "grounding":

        from preflight.db import close_pool, get_pool
        from preflight.evals import grounding as G
        from preflight.evals.grounding_notams import GROUNDING_NOTAMS
        from preflight.verify.nli import HFVerifier

        try:
            with get_pool().connection() as conn:
                res = G.run(conn, HFVerifier(), GROUNDING_NOTAMS)
            run_path, md_path = G.save_run(res)
            print(G.to_markdown(res))
            print(f"written: {run_path}  {md_path}")
        finally:
            close_pool()
        return 0

    if args.cmd == "eval" and args.suite == "embedder":
        from preflight.db import close_pool, get_pool
        from preflight.evals import embedder as EM

        try:
            with get_pool().connection() as conn:
                res = EM.run(conn, models=tuple(args.models) if args.models else EM.DEFAULT_MODELS,
                             size=args.size, limit=args.limit)
        finally:
            close_pool()
        run_path, md_path = EM.save_run(res)
        print(EM.to_markdown(res))
        print(f"written: {run_path}  {md_path}")
        return 0

    if args.cmd == "eval" and args.suite == "forecast":
        from preflight.db import close_pool, get_pool
        from preflight.evals import forecast as F

        try:
            with get_pool().connection() as conn:
                res = F.run(conn, airports=args.airports or None, days=args.days)
            run_path, md_path = F.save_run(res)
            print(F.to_markdown(res))
            print(f"written: {run_path}  {md_path}")
        finally:
            close_pool()
        return 0

    if args.cmd == "eval" and args.suite == "briefing":
        from preflight.db import close_pool, get_pool
        from preflight.evals import briefing as B

        try:
            with get_pool().connection() as conn:
                if args.build or not B.GOLDEN.exists():
                    cases = B.build_cases(conn)
                    B.save_cases(cases)
                    print(f"golden set: {len(cases)} cases → {B.GOLDEN}")
                cases = B.load_cases()
                if args.limit:
                    cases = cases[: args.limit]
                if args.backfill_weather:
                    from preflight.sources.iem import IemAsos

                    filled = B.backfill_weather(
                        conn, cases, source=IemAsos(),
                        log=lambda m: print(m, file=sys.stderr, flush=True))
                    print(f"weather backfill: {filled}", file=sys.stderr)
                res = B.run(conn, cases)
            run_path, md_path = B.save_run(res)
            print(B.to_markdown(res))
            print(f"written: {run_path}  {md_path}")
        finally:
            close_pool()
        return 0

    if args.cmd == "eval":
        from preflight.config import settings
        from preflight.db import close_pool, get_pool
        from preflight.evals import retrieval as R
        from preflight.llm import LLMUnavailable
        from preflight.retrieval.embed import STEmbedder, STReranker

        try:
            with get_pool().connection() as conn:
                if args.build or not R.GOLDEN.exists():
                    qs = R.build_golden(conn)
                    R.save_golden(qs)
                    print(f"golden set: {len(qs)} queries → {R.GOLDEN}")
                queries = R.load_golden()
                if args.kind:
                    queries = [q for q in queries if q.kind == args.kind]
                if args.limit:
                    queries = queries[: args.limit]
                configs = tuple(cfg for cfg in R.CONFIGS if not args.config
                                or cfg[0] in args.config) or R.CONFIGS
                rewrites = None
                if args.rewrite:
                    from preflight.llm import load_llm

                    # Cached rewrites need no model; only uncached queries do.
                    llm = load_llm()
                    cfg = settings()
                    slug = (llm.name if llm else f"ollama/{cfg.ollama_model}"
                            ).replace("/", "-").replace(":", "-")
                    try:
                        rewrites = R.synopsis_rewriter(
                            llm, R.GOLDEN.parent / f"rewrites-{slug}.json")(queries)
                    except LLMUnavailable as e:
                        print(f"error: --rewrite: {e} (start ollama)", file=sys.stderr)
                        return 3
                res = R.run(conn, STEmbedder(), None if args.no_rerank else STReranker(),
                            queries, candidates=args.candidates, configs=configs,
                            rewrites=rewrites)
            run_path, md_path = R.save_run(res)
            print(R.to_markdown(res))
            print(f"written: {run_path}  {md_path}")
        finally:
            close_pool()
        return 0

    if args.cmd == "mcp":
        from preflight.db import close_pool
        from preflight.mcp_server import main as mcp_main

        try:
            mcp_main()
        finally:
            close_pool()
        return 0

    if args.cmd == "dbcheck":
        from preflight.db import close_pool, healthcheck

        try:
            print(healthcheck())
        finally:
            close_pool()
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
