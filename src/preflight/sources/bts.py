"""BTS Airline On-Time Performance — the delay history behind the forecaster.

Monthly bulk files from the Bureau of Transportation Statistics (public domain),
~30 MB zipped, ~600k flights each, published with a roughly three-month lag.
Streamed straight out of the zip and aggregated to one row per (airport, local
scheduled-arrival hour): flight count, cancellations, mean and p90 arrival delay.
"""

from __future__ import annotations

import contextlib
import csv
import io
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple

import httpx

from preflight.config import settings

URL = ("https://transtats.bts.gov/PREZIP/"
       "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip")

_ALASKA = {"ANC", "FAI", "JNU", "BET", "OME", "OTZ", "SCC", "ADQ", "KTN", "SIT", "BRW"}
_HAWAII = {"HNL", "OGG", "KOA", "LIH", "ITO", "MKK", "LNY"}


def iata_to_icao(code: str) -> str | None:
    c = code.strip().upper()
    if len(c) != 3 or not c.isalpha():
        return None
    if c in _ALASKA:
        return "PA" + c[1:] if c[0] == "A" else "P" + c
    if c in _HAWAII:
        return "PH" + c[1:] if c[0] == "H" else "P" + c
    return "K" + c


def raw_dir() -> Path:
    return settings().archive_dir / "bts"


def download(year: int, month: int, *, client: httpx.Client | None = None) -> Path:
    d = raw_dir()
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"ot_{year}_{month}.zip"
    if path.exists() and path.stat().st_size > 0:
        return path
    c = client or httpx.Client(timeout=300.0, follow_redirects=True)
    part = path.with_suffix(".part")
    with c.stream("GET", URL.format(year=year, month=month)) as r, part.open("wb") as f:
        r.raise_for_status()
        for chunk in r.iter_bytes():
            f.write(chunk)
    part.rename(path)
    return path


class HourlyDelay(NamedTuple):
    icao: str
    hour_local: datetime
    flights: int
    cancelled: int
    diverted: int
    mean_arr_delay: float | None
    p90_arr_delay: float | None


def _hour(date: str, hhmm: str) -> datetime | None:
    """BTS local times are 'HHMM' strings; '2400' means midnight at the end of the day."""
    hhmm = (hhmm or "").strip().strip('"')
    if len(hhmm) != 4 or not hhmm.isdigit():
        return None
    h = int(hhmm[:2])
    try:
        base = datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return None
    return base + timedelta(days=1) if h == 24 else base.replace(hour=h)


def aggregate(zip_path: Path) -> Iterator[HourlyDelay]:
    """One month's zip → hourly rows per destination airport."""
    delays: dict[tuple[str, datetime], list[float]] = defaultdict(list)
    counts: dict[tuple[str, datetime], list[int]] = defaultdict(lambda: [0, 0, 0])
    with zipfile.ZipFile(zip_path) as zf:
        name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        with zf.open(name) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8", newline=""))
            for row in reader:
                icao = iata_to_icao(row.get("Dest", ""))
                hour = _hour(row.get("FlightDate", ""), row.get("CRSArrTime", ""))
                if icao is None or hour is None:
                    continue
                key = (icao, hour)
                c = counts[key]
                c[0] += 1
                cancelled = row.get("Cancelled", "0").strip() in {"1", "1.00", "1.0"}
                diverted = row.get("Diverted", "0").strip() in {"1", "1.00", "1.0"}
                c[1] += cancelled
                c[2] += diverted
                if not cancelled and not diverted and row.get("ArrDelay", "").strip():
                    with contextlib.suppress(ValueError):
                        delays[key].append(float(row["ArrDelay"]))
    for key, (n, canc, div) in counts.items():
        d = sorted(delays.get(key, []))
        mean = sum(d) / len(d) if d else None
        p90 = d[min(len(d) - 1, int(len(d) * 0.9))] if d else None
        yield HourlyDelay(key[0], key[1], n, canc, div, mean, p90)
