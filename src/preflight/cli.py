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
    n = isub.add_parser("notams", help="NOTAMs from a text dump (FAA API in step 3)")
    n.add_argument("file", type=Path)

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
                from preflight.ingest.notams import ingest_file

                print(ingest_file(args.file))
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
