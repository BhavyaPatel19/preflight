"""Abstention evaluation: does the briefing say what it does not know?

The cases are constructed, not collected. Each one puts the database into a
specific state for a synthetic route — a METAR three hours old, no TAF across
the arrival window, an airport the archive has never fetched, a fetch in which
the decoder rejected NOTAMs, no retrieval models — builds the briefing, and
checks that exactly the right abstention is there and no other is. The clean
state, with every source present and fresh, must produce no abstention at all:
a system that abstains indiscriminately is as useless as one that never does.

Every case runs inside a transaction that is rolled back, so the eval never
leaves anything behind, and it runs in CI against the empty service database.

Two numbers come out. **Recall** — the share of data-gap cases where the
expected abstention appears — is the headline (README "Abstention" row).
**False-abstention rate** — cases with an abstention nobody asked for — is
the guard against gaming the first.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import psycopg
from psycopg import Connection

from preflight.brief.core import Role, build_briefing
from preflight.brief.precedent import with_precedent
from preflight.db import notams as ndb
from preflight.db import runs as rdb
from preflight.db import weather as wdb
from preflight.decode.notam import DEMO_NOTAMS, parse_notam
from preflight.forecast import delay as delay_mod
from preflight.schemas import Abstention, FlightRequest
from preflight.sources.aviationweather import Metar, Taf

RESULTS = Path("evals/abstention/RESULTS.md")
RUNS = Path("evals/abstention/runs")

T0 = datetime(2026, 9, 11, 2, 30, tzinfo=UTC)
AIRPORTS: dict[Role, str] = {"departure": "KZZY", "destination": "KZZX", "alternate": "KZZW"}
# Synthetic airports need a clock for the delay climatology lookup.
_TZ = {"KZZY": "America/Los_Angeles", "KZZX": "America/New_York", "KZZW": "America/New_York"}

Gap = Literal[
    "none", "metar_missing", "metar_stale", "taf_missing", "taf_expired",
    "notams_none", "notams_inactive", "delay_none", "delay_sparse",
    "parse_failure", "precedent_unavailable", "everything",
]


@dataclass(frozen=True)
class Case:
    id: str
    role: Role                      # which airport of the route carries the gap
    gap: Gap
    expect: tuple[tuple[str, str], ...]    # (topic, reason) abstentions that must appear


@dataclass
class CaseResult:
    case: Case
    abstentions: list[tuple[str, str]]
    hit: bool                       # every expected abstention present
    spurious: list[tuple[str, str]] = field(default_factory=list)


def _expected(role: Role, gap: Gap) -> tuple[tuple[str, str], ...]:
    icao = AIRPORTS[role]
    table: dict[str, tuple[str, str]] = {
        "metar_missing": (f"{icao} current weather", "no_coverage"),
        "metar_stale": (f"{icao} current weather", "stale_source"),
        "taf_missing": (f"{icao} forecast", "no_coverage"),
        "taf_expired": (f"{icao} forecast", "no_coverage"),
        "notams_none": (f"{icao} NOTAMs", "no_coverage"),
        "delay_none": (f"{icao} arrival delay", "no_coverage"),
        "delay_sparse": (f"{icao} arrival delay", "no_coverage"),
        "parse_failure": ("NOTAM decoding", "parse_failure"),
        "precedent_unavailable": ("precedent", "no_coverage"),
    }
    if gap == "everything":
        return tuple(v for k, v in table.items() if k not in {"metar_stale", "taf_expired",
                                                                "delay_sparse"})
    return (table[gap],) if gap in table else ()


def cases() -> list[Case]:
    """One gap at a time per role, plus the clean state and the everything-missing state."""
    out: list[Case] = []
    per_role: dict[Role, tuple[Gap, ...]] = {
        "departure": ("none", "metar_missing", "metar_stale", "notams_none", "notams_inactive"),
        "destination": ("none", "metar_missing", "metar_stale", "taf_missing", "taf_expired",
                        "notams_none", "notams_inactive", "delay_none", "delay_sparse"),
        "alternate": ("none", "metar_missing", "metar_stale", "taf_missing", "taf_expired",
                      "notams_none", "notams_inactive", "delay_none", "delay_sparse"),
    }
    for role, gaps in per_role.items():
        for gap in gaps:
            out.append(Case(f"{role}:{gap}", role, gap, _expected(role, gap)))
    for gap in ("parse_failure", "precedent_unavailable", "everything"):
        out.append(Case(f"destination:{gap}", "destination", gap, _expected("destination", gap)))
    return out


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------

class _NoHits:
    """A retriever that is present but finds nothing — precedent was searched."""

    def search(self, conn: Connection[Any], query: str, **kw: Any) -> list[Any]:
        return []


def _clear(conn: Connection[Any], icao: str) -> None:
    for table in ("notams", "weather_reports", "delay_hourly"):
        conn.execute(f"DELETE FROM {table} WHERE icao = %s", (icao,))  # noqa: S608


def _notam(conn: Connection[Any], icao: str, *, active: bool) -> None:
    # Distinct ids per airport, or the upserts overwrite one another.
    rec = parse_notam(DEMO_NOTAMS[0].replace("KSFO", icao).replace("A1477", f"{icao[-1]}1477"))
    if not active:
        rec = rec.model_copy(update={"effective_from": T0 - timedelta(days=10),
                                     "effective_to": T0 - timedelta(days=5)})
    ndb.upsert(conn, rec)


def _metar(conn: Connection[Any], icao: str, *, age: timedelta) -> None:
    wdb.upsert_metars(conn, [Metar(icao=icao, observed_at=T0 - age, flight_category="VFR",
                                   raw=f"METAR {icao} {T0 - age:%d%H%M}Z 28008KT 10SM CLR 18/09 "
                                       "A3012")])


def _taf(conn: Connection[Any], icao: str, *, covers: bool) -> None:
    start = T0 - timedelta(hours=1) if covers else T0 - timedelta(hours=30)
    wdb.upsert_tafs(conn, [Taf(icao=icao, issued_at=start, valid_from=start,
                               valid_to=start + timedelta(hours=24),
                               raw=f"TAF {icao} {start:%d%H%M}Z 28010KT P6SM SKC")])


def _delays(conn: Connection[Any], icao: str, weeks: int) -> None:
    """``weeks`` history rows at the arrival's local weekday and hour (climatology needs 4)."""
    arrival = T0 + timedelta(hours=3)
    local = delay_mod.local_time(icao, arrival)
    assert local is not None
    for w in range(1, weeks + 1):
        conn.execute(
            "INSERT INTO delay_hourly (icao, hour_local, flights, mean_arr_delay, p90_arr_delay) "
            "VALUES (%s, %s, %s, %s, %s)",
            (icao, local.replace(minute=0, second=0) - timedelta(weeks=w), 40, 12.0 + w, 40.0),
        )


def _ingest_run(conn: Connection[Any], *, unparseable: int) -> None:
    # Newer than any real run, so it is the one the briefing consults.
    now = datetime.now(UTC) + timedelta(minutes=1)
    rdb.record_run(conn, kind="notams", source="file:abstention-eval", started_at=now,
                   finished_at=now, status="ok",
                   counts={"fetched": 3, "stored": 3 - unparseable, "unparseable": unparseable})


def _setup(conn: Connection[Any], case: Case) -> None:
    """Every airport clean, then the case's gap applied to its airport."""
    for role, icao in AIRPORTS.items():
        _clear(conn, icao)
        _notam(conn, icao, active=True)
        _metar(conn, icao, age=timedelta(minutes=10))
        if role != "departure":
            _taf(conn, icao, covers=True)
            _delays(conn, icao, weeks=6)
    _ingest_run(conn, unparseable=0)

    icao, gap = AIRPORTS[case.role], case.gap
    everything = gap == "everything"
    if gap in {"metar_missing", "metar_stale"} or everything:
        conn.execute("DELETE FROM weather_reports WHERE icao = %s AND kind = 'METAR'", (icao,))
        if gap == "metar_stale":
            _metar(conn, icao, age=timedelta(hours=3))
    if gap in {"taf_missing", "taf_expired"} or everything:
        conn.execute("DELETE FROM weather_reports WHERE icao = %s AND kind = 'TAF'", (icao,))
        if gap == "taf_expired":
            _taf(conn, icao, covers=False)
    if gap in {"notams_none", "notams_inactive"} or everything:
        conn.execute("DELETE FROM notams WHERE icao = %s", (icao,))
        if gap == "notams_inactive":
            _notam(conn, icao, active=False)
    if gap in {"delay_none", "delay_sparse"} or everything:
        conn.execute("DELETE FROM delay_hourly WHERE icao = %s", (icao,))
        if gap == "delay_sparse":
            _delays(conn, icao, weeks=3)
    if gap == "parse_failure" or everything:
        _ingest_run(conn, unparseable=2)


@contextmanager
def _synthetic_clocks() -> Iterator[None]:
    added = {k: v for k, v in _TZ.items() if k not in delay_mod.AIRPORT_TZ}
    delay_mod.AIRPORT_TZ.update(added)
    try:
        yield
    finally:
        for k in added:
            delay_mod.AIRPORT_TZ.pop(k, None)


# --------------------------------------------------------------------------
# Run
# --------------------------------------------------------------------------

def run_case(conn: Connection[Any], case: Case) -> CaseResult:
    """Build the briefing in a savepoint that is always rolled back."""
    req = FlightRequest(departure=AIRPORTS["departure"], destination=AIRPORTS["destination"],
                        alternates=(AIRPORTS["alternate"],), off_block=T0)
    retriever: Any = None if case.gap in {"precedent_unavailable", "everything"} else _NoHits()
    got: list[Abstention] = []
    try:
        with conn.transaction():
            _setup(conn, case)
            b = build_briefing(conn, req, now=T0)
            b = with_precedent(conn, b, retriever)
            got = list(b.abstentions)
            raise psycopg.Rollback
    except psycopg.Rollback:
        pass
    pairs: list[tuple[str, str]] = [(a.topic, str(a.reason)) for a in got]
    expected = set(case.expect)
    return CaseResult(case=case, abstentions=pairs, hit=expected <= set(pairs),
                      spurious=[p for p in pairs if p not in expected])


def run(conn: Connection[Any]) -> dict[str, Any]:
    with _synthetic_clocks():
        results = [run_case(conn, c) for c in cases()]
    gap_cases = [r for r in results if r.case.expect]
    by_gap: dict[str, dict[str, int]] = {}
    for r in results:
        g = by_gap.setdefault(r.case.gap, {"cases": 0, "hits": 0, "spurious": 0})
        g["cases"] += 1
        g["hits"] += int(r.hit)
        g["spurious"] += int(bool(r.spurious))
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "cases": len(results),
        "gap_cases": len(gap_cases),
        "recall": round(sum(r.hit for r in gap_cases) / len(gap_cases), 3) if gap_cases else None,
        "false_abstention_rate": round(sum(bool(r.spurious) for r in results) / len(results), 3),
        "by_gap": by_gap,
        "misses": [{"case": r.case.id, "expected": list(r.case.expect), "got": r.abstentions}
                   for r in gap_cases if not r.hit],
        "spurious": [{"case": r.case.id, "unexpected": r.spurious}
                     for r in results if r.spurious],
        "reasons_never_emitted": sorted(
            {"stale_source", "no_coverage", "conflicting_sources", "parse_failure"}
            - {p[1] for r in results for p in r.abstentions}),
    }


def to_markdown(res: dict[str, Any]) -> str:
    lines = [
        "# Abstention evaluation", "",
        f"Run at {res['generated_at']} · {res['cases']} constructed cases, {res['gap_cases']} "
        "with a data gap · synthetic route KZZY → KZZX alt KZZW, every case rolled back", "",
        f"**Recall on data-gap cases: {res['recall']:.3f}** · "
        f"**false-abstention rate: {res['false_abstention_rate']:.3f}**", "",
        "| gap | cases | expected abstention present | spurious abstention |",
        "|---|---:|---:|---:|",
    ]
    for gap, g in res["by_gap"].items():
        lines.append(f"| {gap} | {g['cases']} | {g['hits']} | {g['spurious']} |")
    if res["misses"]:
        lines += ["", "**Misses**", ""]
        lines += [f"- `{m['case']}`: expected {m['expected']}, got {m['got']}"
                  for m in res["misses"]]
    if res["spurious"]:
        lines += ["", "**Spurious**", ""]
        lines += [f"- `{s['case']}`: {s['unexpected']}" for s in res["spurious"]]
    if res["reasons_never_emitted"]:
        lines += ["", f"Reasons in the schema that no rule emits yet: "
                      f"{', '.join(f'`{r}`' for r in res['reasons_never_emitted'])}. "
                      "They are in the case set's vocabulary, not its cases; a rule that "
                      "emits one gets its cases here."]
    lines += ["", "What this measures: whether each *known* kind of data gap produces its "
                  "abstention, and whether a complete data set produces none. What it does not: "
                  "gaps the system has no rule for — those are silent by construction, and the "
                  "time-travel eval's coverage number is where they would surface."]
    return "\n".join(lines) + "\n"


def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    p = RUNS / f"{stamp}.json"
    p.write_text(json.dumps(res, indent=2))
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(to_markdown(res))
    return p, RESULTS
