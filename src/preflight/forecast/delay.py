"""Arrival-delay forecasting over the BTS hourly aggregates.

Two estimators, used for different jobs:

* **Climatology** — the distribution of mean arrival delay for this airport at
  this weekday-and-hour over the history we hold. This is what the *briefing*
  cites, because BTS data lands with a ~3-month lag and a flight next week is
  far beyond any model's honest horizon. It is labelled as climatology.
* **Chronos-Bolt** (zero-shot time-series foundation model) and a
  **seasonal-naive** baseline — compared on a real holdout by
  ``preflight eval forecast`` (MASE, pinball loss). That comparison is the
  point: it shows whether the foundation model earns its place over the
  simplest thing that could work, on this data.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any, NamedTuple

from psycopg import Connection


class Point(NamedTuple):
    hour_local: datetime
    flights: int
    mean_arr_delay: float | None


def series(conn: Connection[Any], icao: str, *, until: datetime | None = None,
           hours: int = 24 * 120) -> list[Point]:
    """Hourly series for an airport, oldest first, gaps filled with flights=0 / delay=None."""
    rows = conn.execute(
        """
        SELECT hour_local, flights, mean_arr_delay FROM delay_hourly
        WHERE icao = %s AND (%s::timestamp IS NULL OR hour_local <= %s)
        ORDER BY hour_local DESC LIMIT %s
        """,
        (icao, until, until, hours),
    ).fetchall()
    if not rows:
        return []
    by_hour = {r[0]: (r[1], r[2]) for r in rows}
    start, end = min(by_hour), max(by_hour)
    out: list[Point] = []
    t = start
    while t <= end:
        f, d = by_hour.get(t, (0, None))
        out.append(Point(t, f, d))
        t += timedelta(hours=1)
    return out


# --------------------------------------------------------------------------
# Climatology
# --------------------------------------------------------------------------

class Climatology(NamedTuple):
    icao: str
    weekday: int                 # 0 = Monday
    hour: int
    samples: int
    p10: float
    p50: float
    p90: float
    flights_per_hour: float
    history_from: datetime
    history_to: datetime


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return math.nan
    i = (len(sorted_vals) - 1) * q
    lo, hi = math.floor(i), math.ceil(i)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (i - lo)


def climatology(conn: Connection[Any], icao: str, at: datetime) -> Climatology | None:
    """Typical arrival delay at ``icao`` for ``at``'s weekday and hour (local clock)."""
    rows = conn.execute(
        """
        SELECT mean_arr_delay, flights, hour_local FROM delay_hourly
        WHERE icao = %s AND EXTRACT(ISODOW FROM hour_local) = %s
          AND EXTRACT(HOUR FROM hour_local) = %s AND mean_arr_delay IS NOT NULL
        """,
        (icao, at.isoweekday(), at.hour),
    ).fetchall()
    if len(rows) < 4:
        return None
    vals = sorted(float(r[0]) for r in rows)
    return Climatology(
        icao=icao, weekday=at.weekday(), hour=at.hour, samples=len(vals),
        p10=_quantile(vals, 0.1), p50=_quantile(vals, 0.5), p90=_quantile(vals, 0.9),
        flights_per_hour=sum(r[1] for r in rows) / len(rows),
        history_from=min(r[2] for r in rows), history_to=max(r[2] for r in rows),
    )


# --------------------------------------------------------------------------
# Forecasters (evaluated; not cited in the briefing)
# --------------------------------------------------------------------------

def seasonal_naive(context: Sequence[float | None], horizon: int, season: int = 168) -> list[float]:
    """Repeat the value from one season (default: a week) earlier; fall back to a day."""
    out: list[float] = []
    hist = list(context)
    for h in range(horizon):
        for s in (season, 24):
            idx = len(hist) - s + (h % s)
            if 0 <= idx < len(hist):
                v = hist[idx]
                if v is not None:
                    out.append(float(v))
                    break
        else:
            last = next((v for v in reversed(hist) if v is not None), None)
            out.append(float(last) if last is not None else 0.0)
    return out


class ChronosForecaster:
    """Zero-shot Chronos-Bolt. Loaded lazily; CPU is fine (a 24 h horizon is ~40 ms)."""

    def __init__(self, model: str = "amazon/chronos-bolt-small"):
        self.model = model
        self._pipe: Any = None

    def _load(self) -> Any:
        if self._pipe is None:
            import torch
            from chronos import BaseChronosPipeline

            self._pipe = BaseChronosPipeline.from_pretrained(
                self.model, device_map="cpu", torch_dtype=torch.float32
            )
        return self._pipe

    def predict(self, context: Sequence[float | None], horizon: int,
                quantiles: Sequence[float] = (0.1, 0.5, 0.9)) -> list[list[float]]:
        """→ ``[[q10, q50, q90], ...]`` per step. Missing values are NaN, which Chronos masks."""
        import torch

        ctx = torch.tensor([[math.nan if v is None else float(v) for v in context]],
                           dtype=torch.float32)
        q, _ = self._load().predict_quantiles(ctx, prediction_length=horizon,
                                              quantile_levels=list(quantiles))
        return [[float(x) for x in step] for step in q[0]]


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def mase(actual: Sequence[float], forecast: Sequence[float],
         context: Sequence[float | None], season: int = 168) -> float | None:
    """Mean absolute scaled error against the in-sample seasonal-naive scale."""
    ctx = [v for v in context if v is not None]
    if len(ctx) <= season:
        return None
    diffs = [abs(ctx[i] - ctx[i - season]) for i in range(season, len(ctx))]
    scale = sum(diffs) / len(diffs)
    if scale == 0:
        return None
    return sum(abs(a - f) for a, f in zip(actual, forecast, strict=True)) / len(actual) / scale


def pinball(actual: float, pred: float, q: float) -> float:
    d = actual - pred
    return max(q * d, (q - 1) * d)


def mean_pinball(actual: Sequence[float], quantile_preds: Sequence[Sequence[float]],
                 quantiles: Sequence[float] = (0.1, 0.5, 0.9)) -> float:
    """Average pinball loss over steps and quantiles — a CRPS proxy from three quantiles."""
    total = 0.0
    for a, preds in zip(actual, quantile_preds, strict=True):
        for q, p in zip(quantiles, preds, strict=True):
            total += pinball(a, p, q)
    return total / (len(actual) * len(quantiles))


# --------------------------------------------------------------------------
# Airport local time (BTS hours are local clock). Watchlist + common alternates.
# --------------------------------------------------------------------------

AIRPORT_TZ: dict[str, str] = {
    "KATL": "America/New_York", "KLAX": "America/Los_Angeles", "KORD": "America/Chicago",
    "KDFW": "America/Chicago", "KDEN": "America/Denver", "KJFK": "America/New_York",
    "KSFO": "America/Los_Angeles", "KSEA": "America/Los_Angeles", "KLAS": "America/Los_Angeles",
    "KMCO": "America/New_York", "KEWR": "America/New_York", "KCLT": "America/New_York",
    "KPHX": "America/Phoenix", "KIAH": "America/Chicago", "KMIA": "America/New_York",
    "KBOS": "America/New_York", "KMSP": "America/Chicago", "KFLL": "America/New_York",
    "KDTW": "America/Detroit", "KPHL": "America/New_York", "KLGA": "America/New_York",
    "KBWI": "America/New_York", "KSLC": "America/Denver", "KSAN": "America/Los_Angeles",
    "KIAD": "America/New_York", "KDCA": "America/New_York", "KMDW": "America/Chicago",
    "KTPA": "America/New_York", "KPDX": "America/Los_Angeles", "PHNL": "Pacific/Honolulu",
    "KOAK": "America/Los_Angeles", "KSJC": "America/Los_Angeles", "KSMF": "America/Los_Angeles",
    "KAUS": "America/Chicago", "KBNA": "America/Chicago", "KSTL": "America/Chicago",
    "KMCI": "America/Chicago", "KRDU": "America/New_York", "KPIT": "America/New_York",
    "KCLE": "America/New_York", "KCVG": "America/New_York", "KIND": "America/Indiana/Indianapolis",
    "KMKE": "America/Chicago", "KSAT": "America/Chicago", "KHOU": "America/Chicago",
    "KDAL": "America/Chicago", "KABQ": "America/Denver", "KRNO": "America/Los_Angeles",
    "KBUR": "America/Los_Angeles", "KONT": "America/Los_Angeles", "KSNA": "America/Los_Angeles",
    "KPBI": "America/New_York", "KRSW": "America/New_York", "KJAX": "America/New_York",
    "KMSY": "America/Chicago", "KMEM": "America/Chicago", "KOMA": "America/Chicago",
    "KBUF": "America/New_York", "KANC": "America/Anchorage", "PANC": "America/Anchorage",
}


def local_time(icao: str, at_utc: datetime) -> datetime | None:
    """``at_utc`` on the airport's local clock (naive), or None if the airport is unknown."""
    from zoneinfo import ZoneInfo

    tz = AIRPORT_TZ.get(icao)
    if tz is None:
        return None
    return at_utc.astimezone(ZoneInfo(tz)).replace(tzinfo=None)
