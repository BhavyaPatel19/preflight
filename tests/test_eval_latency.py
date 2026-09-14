"""Latency bench: per-stage percentiles from graph timings, warm-up excluded."""

from contextlib import nullcontext
from datetime import UTC, datetime

import pytest

from preflight.evals.latency import BenchResult, bench, render_markdown
from preflight.graph import Deps, build_graph
from preflight.schemas import FlightRequest

T0 = datetime(2026, 9, 11, 2, 30, tzinfo=UTC)


def test_percentiles_and_markdown():
    r = BenchResult(runs=4, options={"precedent": False})
    r.timings = [{"gather": 10}, {"gather": 20}, {"gather": 30}, {"gather": 100}]
    r.totals = [11, 21, 31, 101]
    assert r.percentiles("gather") == (25, 90)              # inclusive quantiles, rounded
    assert r.percentiles("total") == (26, 90)
    assert r.percentiles("narrate") is None                 # stage never ran
    md = render_markdown(r, label="x")
    assert "| gather | 25 | 90 |" in md and "narrate" not in md and "precedent=off" in md


def test_single_run_percentiles_are_the_value():
    r = BenchResult(runs=1, options={})
    r.timings, r.totals = [{"gather": 7}], [9]
    assert r.percentiles("gather") == (7, 7) and r.percentiles("total") == (9, 9)


@pytest.mark.db
def test_bench_runs_the_graph_and_skips_the_warmup(db):
    g = build_graph(Deps(connect=lambda: nullcontext(db), now=lambda: T0))
    req = FlightRequest(departure="KSFO", destination="KJFK", off_block=T0)
    res = bench(g, req, options={"precedent": False, "verify": False, "narrative": False},
                runs=2, warmup=True)
    assert len(res.totals) == 2 and all("gather" in t for t in res.timings)
    assert res.percentiles("precedent") is None
