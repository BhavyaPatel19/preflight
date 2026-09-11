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
