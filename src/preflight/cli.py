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
    eb = evsub.add_parser("briefing", help="time-travel briefing eval on NTSB-derived cases")
    eb.add_argument("--build", action="store_true", help="(re)build evals/briefing/golden.jsonl")
    eb.add_argument("--limit", type=int)

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
    b.add_argument("--json", action="store_true", help="emit JSON instead of text")
    b.add_argument("--no-precedent", action="store_true",
                   help="skip the prior-report search (faster; no model load)")

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
            else:
                import asyncio

                from preflight.ingest.notams import ingest_notams
                from preflight.sources.notams import (
                    FileSource,
                    NasaDipSource,
                    NotamSource,
                    SourceUnavailable,
                )

                src: NotamSource
                if args.file:
                    src = FileSource(*args.file)
                elif args.source == "nasa-dip":
                    from preflight.config import settings

                    src = NasaDipSource(settings().nasa_dip_base_url, settings().nasa_dip_token)
                else:
                    print("error: give --file PATH or --source nasa-dip ICAO...", file=sys.stderr)
                    return 2
                try:
                    print(asyncio.run(ingest_notams(src, args.icao)))
                except SourceUnavailable as e:
                    print(f"source unavailable: {e}", file=sys.stderr)
                    return 3
        finally:
            close_pool()
        return 0

    if args.cmd == "brief":
        from datetime import datetime

        from preflight.brief import build_briefing, load_retriever, render_text, with_precedent
        from preflight.db import close_pool, get_pool
        from preflight.schemas import FlightRequest

        req = FlightRequest(
            departure=args.departure.upper(), destination=args.destination.upper(),
            alternates=tuple(a.upper() for a in args.alt),
            off_block=datetime.fromisoformat(args.off_block.replace("Z", "+00:00")),
            aircraft_type=args.aircraft_type,
        )
        try:
            with get_pool().connection() as conn:
                briefing = build_briefing(conn, req)
                if not args.no_precedent:
                    briefing = with_precedent(conn, briefing, load_retriever())
        finally:
            close_pool()
        print(briefing.model_dump_json(indent=2) if args.json else render_text(briefing))
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
                res = B.run(conn, cases)
            run_path, md_path = B.save_run(res)
            print(B.to_markdown(res))
            print(f"written: {run_path}  {md_path}")
        finally:
            close_pool()
        return 0

    if args.cmd == "eval":
        from preflight.db import close_pool, get_pool
        from preflight.evals import retrieval as R
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
                res = R.run(conn, STEmbedder(), None if args.no_rerank else STReranker(),
                            queries, candidates=args.candidates)
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
