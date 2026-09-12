from __future__ import annotations

from datetime import date
from time import perf_counter
from typing import Any

import structlog

from preflight.db import get_pool
from preflight.sources import bts

log = structlog.get_logger(__name__)

_UPSERT = """
INSERT INTO delay_hourly (icao, hour_local, flights, cancelled, diverted, mean_arr_delay,
                          p90_arr_delay)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (icao, hour_local) DO UPDATE SET
    flights = EXCLUDED.flights, cancelled = EXCLUDED.cancelled, diverted = EXCLUDED.diverted,
    mean_arr_delay = EXCLUDED.mean_arr_delay, p90_arr_delay = EXCLUDED.p90_arr_delay
"""


def months_back(n: int, *, latest: tuple[int, int]) -> list[tuple[int, int]]:
    """``n`` (year, month) pairs ending at ``latest``, oldest first."""
    y, m = latest
    out: list[tuple[int, int]] = []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    return out[::-1]


def ingest_delays(*, months: int = 12, latest: tuple[int, int] | None = None) -> dict[str, Any]:
    """Download ``months`` of BTS on-time data ending at ``latest`` and store hourly aggregates."""
    t0 = perf_counter()
    if latest is None:
        today = date.today()
        # BTS publishes with ~3 months of lag; the caller can override.
        y, m = today.year, today.month - 3
        if m <= 0:
            y, m = y - 1, m + 12
        latest = (y, m)
    rows_total = 0
    done: list[str] = []
    with get_pool().connection() as conn:
        for year, month in months_back(months, latest=latest):
            path = bts.download(year, month)
            n = 0
            for r in bts.aggregate(path):
                conn.execute(_UPSERT, tuple(r))
                n += 1
            conn.commit()
            rows_total += n
            done.append(f"{year}-{month:02d}")
            log.info("delays.month", month=done[-1], hourly_rows=n,
                     elapsed_s=round(perf_counter() - t0))
    return {"months": done, "hourly_rows": rows_total, "seconds": round(perf_counter() - t0)}
