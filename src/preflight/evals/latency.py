"""Latency benchmark: wall time per graph stage over repeated briefings.

Reports p50/p95 per node and for the whole run, so a change to one stage can be
credited (or blamed) precisely. The first run is a warm-up and is excluded when
``warmup`` is set, because model loads and the first MPS kernels dominate it and
say nothing about steady state.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from preflight.graph import Options, run_briefing
from preflight.schemas import FlightRequest

STAGES = ("gather", "precedent", "verify", "narrate")


@dataclass
class BenchResult:
    runs: int
    options: Options
    timings: list[dict[str, int]] = field(default_factory=list)   # per run, node → ms
    totals: list[int] = field(default_factory=list)               # per run, wall ms
    findings: int = 0
    llm: str | None = None

    def percentiles(self, key: str) -> tuple[int, int] | None:
        vals = [t[key] for t in self.timings if key in t] if key != "total" else self.totals
        if not vals:
            return None
        return _p(vals, 50), _p(vals, 95)


def _p(vals: list[int], pct: int) -> int:
    if len(vals) == 1:
        return vals[0]
    qs = statistics.quantiles(vals, n=100, method="inclusive")
    return int(round(qs[pct - 1]))


def bench(graph: Any, req: FlightRequest, *, options: Options, runs: int = 3,
          warmup: bool = True) -> BenchResult:
    """Run the same briefing ``runs`` times (fresh thread each) and collect node timings."""
    res = BenchResult(runs=runs, options=options)
    for i in range(runs + (1 if warmup else 0)):
        t0 = perf_counter()
        b, state = run_briefing(graph, req, options=options)
        total = int((perf_counter() - t0) * 1000)
        if warmup and i == 0:
            continue
        res.timings.append(dict(state.get("timings", {})))
        res.totals.append(total)
        res.findings = len(b.findings)
        res.llm = b.llm
    return res


def render_markdown(res: BenchResult, *, label: str = "") -> str:
    opts = ", ".join(f"{k}={'on' if v else 'off'}" for k, v in sorted(res.options.items()))
    head = [f"**{label}**" if label else "",
            f"{res.runs} runs after warm-up · {opts} · {res.findings} findings · "
            f"llm {res.llm or 'none'} · {datetime.now(UTC):%Y-%m-%dT%H:%MZ}", "",
            "| stage | p50 ms | p95 ms |", "|---|---:|---:|"]
    rows = []
    for key in (*STAGES, "total"):
        pp = res.percentiles(key)
        if pp:
            rows.append(f"| {key} | {pp[0]:,} | {pp[1]:,} |")
    return "\n".join(line for line in (*head, *rows) if line is not None).strip() + "\n"
