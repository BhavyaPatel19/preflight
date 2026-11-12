"""Record briefings from a running Preflight API for the static replay demo.

The hosted demo (GitHub Pages) cannot run Postgres, the 316k-chunk corpus or a local model,
so it replays briefings captured here, event for event, from a real local run.

    preflight serve                       # in one terminal, with the database and Ollama up
    python scripts/record_demo.py         # in another; writes demo/flights.json + demo/briefings/

Flights are `DEP-DEST[/ALT,ALT]@OFFBLOCK_UTC[:TYPE]`, e.g. `KSFO-KJFK/KBOS@2026-09-11T02:30Z:A320`.
Every recorded event is validated against the schemas by tests/test_demo_recordings.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

DEFAULT_FLIGHTS = [
    # The bundled sample NOTAMs cover KSFO and KJFK; KLAX exercises precedent and weather only.
    "KSFO-KJFK/KBOS@2026-09-11T02:30Z:A320",
    "KJFK-KSFO/KOAK@2026-09-11T05:00Z:B738",
    "KSFO-KLAX/KSAN@2026-09-11T01:00Z:A320",
]

AS_OF_BEFORE = timedelta(minutes=60)

_FLIGHT = re.compile(
    r"^(?P<dep>[A-Z]{4})-(?P<dest>[A-Z]{4})(?:/(?P<alt>[A-Z]{4}(?:,[A-Z]{4})*))?"
    r"@(?P<off>\d{4}-\d{2}-\d{2}T\d{2}:\d{2})Z?(?::(?P<type>\w+))?$"
)


def parse_flight(spec: str) -> dict[str, str]:
    m = _FLIGHT.match(spec.strip().upper())
    if not m:
        raise SystemExit(
            f"bad flight spec {spec!r}; want DEP-DEST[/ALT,ALT]@YYYY-MM-DDTHH:MMZ[:TYPE]"
        )
    off = datetime.fromisoformat(m["off"]).replace(tzinfo=UTC)
    return {
        "departure": m["dep"],
        "destination": m["dest"],
        "alternates": m["alt"] or "",
        "off_block": m["off"] + ":00Z",
        "aircraft_type": m["type"] or "",
        # Brief as a dispatcher would have, an hour before off-block (the time-travel eval's
        # snapshot rule), so the recording shows the weather and NOTAMs then in force.
        "as_of": (off - AS_OF_BEFORE).strftime("%Y-%m-%dT%H:%M:00Z"),
    }


def slug(params: dict[str, str]) -> str:
    return f"{params['departure']}-{params['destination']}-{params['off_block'][:16]}".replace(
        ":", ""
    ).lower()


def record(client: httpx.Client, params: dict[str, str]) -> dict[str, Any]:
    """Consume one SSE briefing stream; keep each event and its offset from the request."""
    events: list[dict[str, Any]] = []
    started = time.monotonic()
    name: str | None = None
    with client.stream("GET", "/brief/stream", params={**params, "precedent": "true"}) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("event:"):
                name = line.split(":", 1)[1].strip()
            elif line.startswith("data:") and name:
                events.append({
                    "event": name,
                    "t_ms": round((time.monotonic() - started) * 1000),
                    "data": json.loads(line.split(":", 1)[1].strip()),
                })
                name = None
    if not events or events[-1]["event"] != "done":
        raise RuntimeError(f"stream for {params} ended without a 'done' event")
    return {"request": params, "recorded_at": datetime.now(UTC).isoformat(), "events": events}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("flights", nargs="*", default=DEFAULT_FLIGHTS, help="flight specs")
    ap.add_argument("--base", default="http://localhost:8000", help="running Preflight API")
    ap.add_argument("--out", type=Path, default=Path("demo"), help="output directory")
    args = ap.parse_args(argv)

    (args.out / "briefings").mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.base, timeout=httpx.Timeout(10.0, read=300.0)) as client:
        for spec in args.flights:
            params = parse_flight(spec)
            print(f"recording {spec} ...", file=sys.stderr, flush=True)
            rec = record(client, params)
            done = rec["events"][-1]["data"]
            name = slug(params)
            (args.out / "briefings" / f"{name}.json").write_text(json.dumps(rec, indent=1) + "\n")
            manifest.append({
                "id": name,
                "label": f"{params['departure']} → {params['destination']}"
                + (f" (alt {params['alternates']})" if params["alternates"] else ""),
                "request": params,
                "findings": done["findings"],
                "abstentions": done["abstentions"],
                "wall_ms": rec["events"][-1]["t_ms"],     # whole briefing, request to done
                "recorded_at": rec["recorded_at"],
            })
            print(f"  {done['findings']} findings, {done['abstentions']} abstentions, "
                  f"{rec['events'][-1]['t_ms']} ms wall", file=sys.stderr)
    (args.out / "flights.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"wrote {len(manifest)} recordings to {args.out}/", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
