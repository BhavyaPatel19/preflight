"""Delay-forecast evaluation: Chronos-Bolt vs seasonal-naive vs climatology on a real holdout.

Rolling-origin backtest. For each airport and each of the last ``days`` days,
the origin is local midnight; each forecaster sees the history before it and
predicts the next 24 hours of mean arrival delay. Scored on hours that had
flights. MASE is scaled by the in-sample seasonal-naive error, so 1.0 means
"no better than repeating last week"; mean pinball loss over the 10/50/90
quantiles is the CRPS proxy for the probabilistic forecasters.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

from psycopg import Connection

from preflight.config import settings
from preflight.forecast.delay import (
    ChronosForecaster,
    Point,
    _quantile,
    mase,
    mean_pinball,
    seasonal_naive,
    series,
)

RESULTS = Path("evals/forecast/RESULTS.md")
RUNS = Path("evals/forecast/runs")
CONTEXT_HOURS = 24 * 60         # 60 days of context per origin
MIN_HISTORY_HOURS = 24 * 90


def _climatology_forecast(
    history: list[Point], origin: datetime, horizon: int
) -> list[list[float]]:
    """Weekday-hour quantiles from the history — the estimator the briefing cites."""
    out: list[list[float]] = []
    for h in range(horizon):
        t = origin + timedelta(hours=h)
        vals = sorted(p.mean_arr_delay for p in history
                      if p.mean_arr_delay is not None and p.hour_local.weekday() == t.weekday()
                      and p.hour_local.hour == t.hour)
        out.append([_quantile(vals, 0.1), _quantile(vals, 0.5), _quantile(vals, 0.9)]
                   if len(vals) >= 4 else [0.0, 0.0, 0.0])
    return out


def run(conn: Connection[Any], *, airports: list[str] | None = None, days: int = 14,
        chronos: ChronosForecaster | None = None) -> dict[str, Any]:
    airports = airports or settings().watchlist
    fc = chronos or ChronosForecaster()
    scores: dict[str, dict[str, list[float]]] = {
        "seasonal-naive": {"mase": []}, "climatology": {"mase": [], "pinball": []},
        "chronos-bolt": {"mase": [], "pinball": []},
    }
    per_airport: dict[str, dict[str, float]] = {}
    origins = 0

    for icao in airports:
        pts = series(conn, icao, hours=24 * 400)
        if len(pts) < MIN_HISTORY_HOURS + 24 * days:
            continue
        idx = {p.hour_local: i for i, p in enumerate(pts)}
        last_day = pts[-1].hour_local.replace(hour=0, minute=0)
        air: dict[str, list[float]] = {"seasonal-naive": [], "chronos-bolt": [], "climatology": []}
        for d in range(days, 0, -1):
            origin = last_day - timedelta(days=d - 1)
            i0 = idx.get(origin)
            if i0 is None or i0 + 24 > len(pts):
                continue
            history = pts[max(0, i0 - CONTEXT_HOURS):i0]
            context = [p.mean_arr_delay for p in history]
            future = pts[i0:i0 + 24]
            keep = [k for k, p in enumerate(future) if p.mean_arr_delay is not None]
            if len(keep) < 12:
                continue
            actual = [float(future[k].mean_arr_delay or 0.0) for k in keep]

            sn = seasonal_naive(context, 24)
            cl = _climatology_forecast(pts[max(0, i0 - 24 * 400):i0], origin, 24)
            ch = fc.predict(context, 24)
            for name, point, quant in (
                ("seasonal-naive", sn, None),
                ("climatology", [q[1] for q in cl], cl),
                ("chronos-bolt", [q[1] for q in ch], ch),
            ):
                m = mase(actual, [point[k] for k in keep], context)
                if m is not None:
                    scores[name]["mase"].append(m)
                    air[name].append(m)
                if quant is not None:
                    scores[name]["pinball"].append(mean_pinball(actual, [quant[k] for k in keep]))
            origins += 1
        if air["chronos-bolt"]:
            per_airport[icao] = {k: round(mean(v), 3) for k, v in air.items() if v}

    summary = {name: {k: (round(mean(v), 3) if v else None) for k, v in d.items()}
               for name, d in scores.items()}
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        sha = "unknown"
    span = conn.execute(
        "SELECT min(hour_local), max(hour_local), count(*) FROM delay_hourly"
    ).fetchone()
    assert span is not None
    return {
        "ran_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "git_sha": sha, "model": fc.model, "days": days, "origins": origins,
        "airports": len(per_airport), "data_from": str(span[0])[:10], "data_to": str(span[1])[:10],
        "hourly_rows": span[2], "summary": summary, "per_airport": per_airport,
    }


def to_markdown(res: dict[str, Any]) -> str:
    s = res["summary"]

    def f(x: float | None) -> str:
        return "—" if x is None else f"{x:.3f}"
    lines = [
        "# Delay-forecast evaluation", "",
        f"Run `{res['git_sha']}` at {res['ran_at']} · BTS hourly arrival delay "
        f"{res['data_from']} → {res['data_to']} ({res['hourly_rows']:,} airport-hours) · "
        f"rolling-origin backtest, {res['days']} daily origins × {res['airports']} airports = "
        f"{res['origins']} forecasts of 24 h", "",
        "| forecaster | MASE ↓ | mean pinball (q10/50/90) ↓ |", "|---|---:|---:|",
        f"| seasonal-naive (last week, same hour) | {f(s['seasonal-naive']['mase'])} | — |",
        f"| climatology (weekday-hour quantiles) | {f(s['climatology']['mase'])} | "
        f"{f(s['climatology']['pinball'])} |",
        f"| `{res['model']}` zero-shot | {f(s['chronos-bolt']['mase'])} | "
        f"{f(s['chronos-bolt']['pinball'])} |",
        "", "MASE < 1 beats repeating last week; the README target is < 0.85.", "",
        "| airport | seasonal-naive | climatology | chronos-bolt |", "|---|---:|---:|---:|",
    ]
    for icao, d in sorted(res["per_airport"].items()):
        lines.append(f"| {icao} | {f(d.get('seasonal-naive'))} | {f(d.get('climatology'))} | "
                     f"{f(d.get('chronos-bolt'))} |")
    lines += [
        "",
        "The briefing cites climatology, not the model: BTS lands with a ~3-month lag, and a",
        "flight next week is beyond any honest horizon. The model earns its place, or does not,",
        "on this table.",
    ]
    return "\n".join(lines) + "\n"


def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = res["ran_at"].replace(":", "").replace("-", "")[:15]
    p = RUNS / f"{stamp}-{res['git_sha']}.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(to_markdown(res))
    return p, RESULTS
