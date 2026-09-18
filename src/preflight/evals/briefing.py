"""Time-travel briefing evaluation: case construction and scoring.

**Positives** are NTSB events (2008→) tied to an airport whose investigated
findings name a hazard a preflight briefing could plausibly have surfaced —
weather, wildlife, an airport facility (lighting, navaid), runway condition or
incursion. Off-airport trees, wires and terrain are excluded: no NOTAM or
forecast would have covered them. Each case reconstructs the flight as a
``FlightRequest`` and a ``snapshot_at`` sixty minutes before the event.

**Negatives** are matched controls: the same airport, the same hour of day,
the same month, on a day with no NTSB event there. Alert fatigue is the
failure mode that matters, so precision is scored on the same footing as
recall.

**Scoring** replays the deterministic briefing against what the database holds
for the snapshot. A case is *covered* only if there is data for its window —
any NOTAM at the airport or a METAR within the staleness threshold. Recall
and false-alarm rate are computed over covered cases; coverage itself is
reported, because the raw archive only began on 2026-09-11 and grows from
there (docs/adr/0002). Judged relevance of the *precedent* claims is separate
and needs a judge; this suite scores hazards, not prose.
"""

from __future__ import annotations

import json
import random
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

from psycopg import Connection

from preflight.brief.core import build_briefing
from preflight.config import settings
from preflight.evals import summary
from preflight.schemas import Briefing, FlightRequest, Severity

GOLDEN = Path("evals/briefing/golden.jsonl")
RESULTS = Path("evals/briefing/RESULTS.md")
RUNS = Path("evals/briefing/runs")

# A far-away, busy partner airport so the case's own airport is the one under test.
PARTNER = "KDEN"
DEPARTURE_PHASES = {"taxi", "takeoff", "climb"}

# (regex over finding descriptions or occurrences) → briefing category
_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"weather/phenomena-(Ceiling|Visibility|Fog|Low visibility|IMC|Precip|Rain|Snow|"
                r"Turbulence|Icing|Thunderstorm|Windshear|Wake)", re.I), "weather"),
    (re.compile(r"weather/phenomena-Wind", re.I), "weather"),
    (re.compile(r"Conducive to carburetor icing|Density altitude", re.I), "weather"),
    (re.compile(r"Animal\(s\)/bird\(s\)|Birdstrike|Wildlife encounter", re.I), "wildlife"),
    (re.compile(r"Airport facilities.*Light|Lighting", re.I), "lighting"),
    (re.compile(r"NAVAID|Navigation aid|Instrument landing", re.I), "navaid"),
    (re.compile(r"Runway/landing area condition|Runway/taxiway/apron|Runway incursion", re.I),
     "runway"),
)


@dataclass(frozen=True)
class Case:
    id: str
    label: str                    # positive | negative
    source_ref: str | None        # NTSB number
    airport: str
    role: str                     # departure | destination
    partner: str
    snapshot_at: str              # ISO-8601 UTC, event time − 60 min
    off_block: str                # ISO-8601 UTC
    implicated: str | None        # briefing category (positives)
    evidence: tuple[str, ...]     # the finding/occurrence strings that decided it
    matched_to: str | None = None
    wx_basic: str | None = None
    light: str | None = None
    highest_injury: str | None = None


def classify(
    findings: Sequence[str], occurrences: Sequence[str]
) -> tuple[str, tuple[str, ...]] | None:
    """Briefing category implicated by the investigation, with the strings that decided it."""
    for pattern, category in _RULES:
        hits = tuple(s for s in (*findings, *occurrences) if pattern.search(s))
        if hits:
            return category, hits[:4]
    return None


def _flight_times(event_at: datetime, role: str) -> tuple[datetime, datetime]:
    """(snapshot_at, off_block). Snapshot is T−60 min. Off-block places the event
    inside the briefing window for that role (see brief.core.windows)."""
    snapshot = event_at - timedelta(minutes=60)
    off_block = event_at if role == "departure" else event_at - timedelta(hours=2)
    return snapshot, off_block


def build_cases(
    conn: Connection[Any], *, n_positive: int = 300, seed: int = 42
) -> list[Case]:
    rng = random.Random(seed)
    rows = conn.execute(
        """
        SELECT external_id, icao, published, metadata
        FROM documents WHERE source = 'ntsb' AND icao IS NOT NULL
          AND metadata->>'local_time' IS NOT NULL
        ORDER BY external_id
        """
    ).fetchall()

    positives: list[Case] = []
    by_airport_dates: dict[str, set[date]] = {}
    for ev_id, icao, published, meta in rows:
        by_airport_dates.setdefault(icao, set()).add(published)
        findings = [f["description"] for f in meta.get("findings", [])]
        verdict = classify(findings, meta.get("occurrences", []))
        if verdict is None:
            continue
        category, evidence = verdict
        hhmm = meta["local_time"]
        try:
            event_at = datetime.combine(published, time(int(hhmm[:2]), int(hhmm[2:])), tzinfo=UTC)
        except ValueError:
            continue
        phases = set(meta.get("phases", []))
        role = "departure" if phases and phases <= DEPARTURE_PHASES else "destination"
        snapshot, off_block = _flight_times(event_at, role)
        positives.append(Case(
            id=f"pos-{ev_id}", label="positive", source_ref=meta.get("ntsb_no"),
            airport=icao, role=role, partner=PARTNER if icao != PARTNER else "KORD",
            snapshot_at=snapshot.isoformat(), off_block=off_block.isoformat(),
            implicated=category, evidence=evidence,
            wx_basic=meta.get("wx_basic"), light=meta.get("light"),
            highest_injury=meta.get("highest_injury"),
        ))

    # Stratify: even share per category, filled from the rest at random.
    rng.shuffle(positives)
    per_cat: dict[str, list[Case]] = {}
    for c in positives:
        per_cat.setdefault(c.implicated or "", []).append(c)
    quota = max(1, n_positive // max(1, len(per_cat)))
    chosen: list[Case] = []
    for cases in per_cat.values():
        chosen.extend(cases[:quota])
    rest = [c for c in positives if c not in chosen]
    chosen.extend(rest[: max(0, n_positive - len(chosen))])
    chosen = chosen[:n_positive]

    # Matched negatives: same airport, hour and month; a day with no NTSB event there.
    negatives: list[Case] = []
    for c in chosen:
        ev = datetime.fromisoformat(c.snapshot_at) + timedelta(minutes=60)
        busy = by_airport_dates.get(c.airport, set())
        for _ in range(50):
            year = rng.randint(2008, 2025)
            day = rng.randint(1, 28)
            cand = ev.replace(year=year, day=day)
            if cand.date() in busy or cand.date() == ev.date():
                continue
            snapshot, off_block = _flight_times(cand, c.role)
            negatives.append(Case(
                id=f"neg-{c.id[4:]}", label="negative", source_ref=None, airport=c.airport,
                role=c.role, partner=c.partner, snapshot_at=snapshot.isoformat(),
                off_block=off_block.isoformat(), implicated=None, evidence=(), matched_to=c.id,
            ))
            break
    return chosen + negatives


def save_cases(cases: Sequence[Case], path: Path = GOLDEN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for c in cases:
            f.write(json.dumps(asdict(c)) + "\n")


def load_cases(path: Path = GOLDEN) -> list[Case]:
    out: list[Case] = []
    with path.open() as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                d["evidence"] = tuple(d["evidence"])
                out.append(Case(**d))
    return out


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

ALARM = {Severity.HIGH, Severity.MEDIUM}


def request_for(c: Case) -> FlightRequest:
    dep, dest = (c.airport, c.partner) if c.role == "departure" else (c.partner, c.airport)
    return FlightRequest(departure=dep, destination=dest,
                         off_block=datetime.fromisoformat(c.off_block))


def covered(conn: Connection[Any], c: Case) -> bool:
    """Is there any data for this case's airport around its snapshot?"""
    snap = datetime.fromisoformat(c.snapshot_at)
    stale = timedelta(minutes=settings().metar_stale_after_minutes)
    row = conn.execute(
        """
        SELECT
          EXISTS (SELECT 1 FROM notams WHERE icao = %(icao)s
                  AND (effective_from IS NULL OR effective_from <= %(hi)s)
                  AND (permanent OR effective_to IS NULL OR effective_to >= %(lo)s)) AS has_notam,
          EXISTS (SELECT 1 FROM weather_reports WHERE icao = %(icao)s AND kind = 'METAR'
                  AND issued_at BETWEEN %(wlo)s AND %(snap)s) AS has_metar
        """,
        {"icao": c.airport, "lo": snap - timedelta(hours=8), "hi": snap + timedelta(hours=8),
         "wlo": snap - stale, "snap": snap},
    ).fetchone()
    assert row is not None
    return bool(row[0] or row[1])


def score_case(c: Case, b: Briefing) -> dict[str, Any]:
    mine = [f for f in b.findings if f.airport == c.airport]
    alarms = [f for f in mine if f.severity in ALARM]
    if c.label == "positive":
        hit = [f for f in mine if f.category == c.implicated and f.severity is not Severity.INFO]
        rank = next((i for i, f in enumerate(b.ranked(), 1) if f in hit), None)
        return {"hazard_found": bool(hit), "hazard_rank": rank, "alarms": len(alarms),
                "abstained": any(c.airport in a.topic for a in b.abstentions)}
    return {"false_alarm": bool(alarms), "alarms": len(alarms),
            "abstained": any(c.airport in a.topic for a in b.abstentions)}


def backfill_weather(
    conn: Connection[Any], cases: Sequence[Case], *, source: Any, hours_before: float = 3.0,
    commit: bool = True, log: Callable[[str], None] | None = None,
) -> dict[str, int]:
    """Pull the METARs around each case's snapshot from a historical archive into the weather
    table, so the time-travel briefing has what a briefing at that moment would have had.

    Only cases whose implicated hazard (or whose matched positive's) is weather are fetched —
    that is the slice public data can cover; the NOTAM-implicated slices stay uncovered and are
    reported as such. Idempotent: airports already holding a METAR inside the staleness window
    before the snapshot are skipped, so a rerun costs nothing. Commits per case so a long pull
    survives interruption — pass ``commit=False`` inside a transaction you own (tests).
    """
    from preflight.db import weather as wdb

    stale = timedelta(minutes=settings().metar_stale_after_minutes)
    weather_ids = {c.id for c in cases if c.label == "positive" and c.implicated == "weather"}
    todo = [c for c in cases if c.id in weather_ids or c.matched_to in weather_ids]
    counts = {"cases": len(todo), "fetched": 0, "skipped": 0, "reports": 0, "unavailable": 0}
    for i, c in enumerate(todo, 1):
        snap = datetime.fromisoformat(c.snapshot_at)
        have = wdb.latest(conn, c.airport, "METAR", as_of=snap)
        if have is not None and have.issued_at >= snap - stale:
            counts["skipped"] += 1
            continue
        try:
            reports = source.fetch_metars(c.airport, snap - timedelta(hours=hours_before),
                                          snap + timedelta(minutes=5))
        except Exception as e:  # noqa: BLE001 — one dead station must not end the backfill
            counts["unavailable"] += 1
            if log:
                log(f"{c.airport} {c.snapshot_at[:16]}: {e}")
            continue
        counts["fetched"] += 1
        counts["reports"] += wdb.upsert_metars(conn, reports)
        if commit:
            conn.commit()
        if log and i % 25 == 0:
            log(f"{i}/{len(todo)} cases · {counts['reports']} reports")
    return counts


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run(conn: Connection[Any], cases: Sequence[Case]) -> dict[str, Any]:
    per: list[dict[str, Any]] = []
    for c in cases:
        cov = covered(conn, c)
        rec: dict[str, Any] = {"id": c.id, "label": c.label, "airport": c.airport,
                               "implicated": c.implicated, "covered": cov}
        if cov:
            b = build_briefing(conn, request_for(c), now=datetime.fromisoformat(c.snapshot_at))
            rec.update(score_case(c, b))
        per.append(rec)

    pos = [r for r in per if r["label"] == "positive"]
    neg = [r for r in per if r["label"] == "negative"]
    pos_c = [r for r in pos if r["covered"]]
    neg_c = [r for r in neg if r["covered"]]
    by_cat: dict[str, dict[str, Any]] = {}
    for r in pos:
        d = by_cat.setdefault(r["implicated"], {"cases": 0, "covered": 0, "found": 0})
        d["cases"] += 1
        d["covered"] += r["covered"]
        d["found"] += bool(r.get("hazard_found"))
    for d in by_cat.values():
        d["recall"] = round(d["found"] / d["covered"], 3) if d["covered"] else None
    # Negatives are matched to a positive; score them beside the category they control for.
    matched = {c.id: c.matched_to for c in cases if c.label == "negative"}
    cat_of = {c.id: c.implicated for c in cases if c.label == "positive"}
    neg_by_cat: dict[str, dict[str, Any]] = {}
    for r in neg_c:
        cat = cat_of.get(matched.get(r["id"]) or "") or "unmatched"
        d = neg_by_cat.setdefault(cat, {"covered": 0, "false_alarms": 0})
        d["covered"] += 1
        d["false_alarms"] += bool(r.get("false_alarm"))
    for d in neg_by_cat.values():
        d["rate"] = round(d["false_alarms"] / d["covered"], 3) if d["covered"] else None
    misses = [r for r in pos_c if not r.get("hazard_found")]
    return {
        "negatives_by_category": neg_by_cat,
        "misses": [{"id": r["id"], "airport": r["airport"], "abstained": r.get("abstained")}
                   for r in misses[:400]],
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "cases": {"positive": len(pos), "negative": len(neg)},
        "coverage": {"positive": len(pos_c), "negative": len(neg_c)},
        "hazard_recall": (sum(bool(r.get("hazard_found")) for r in pos_c) / len(pos_c)
                          if pos_c else None),
        "false_alarm_rate": (sum(bool(r.get("false_alarm")) for r in neg_c) / len(neg_c)
                             if neg_c else None),
        "by_category": by_cat,
        "earliest_case": min(c.snapshot_at for c in cases)[:10] if cases else None,
        "latest_case": max(c.snapshot_at for c in cases)[:10] if cases else None,
        "archive_started": "2026-09-11",
    }


def to_markdown(res: dict[str, Any]) -> str:
    def pct(x: float | None) -> str:
        return "—" if x is None else f"{x:.3f}"
    lines = [
        "# Briefing evaluation (time-travel)", "",
        f"Run `{res['git_sha']}` at {res['ran_at']} · {res['cases']['positive']} positives "
        f"(NTSB events {res['earliest_case']} → {res['latest_case']}) + "
        f"{res['cases']['negative']} matched negatives.", "",
        "| metric | value |", "|---|---:|",
        f"| covered positives (data exists for the snapshot) | {res['coverage']['positive']} / "
        f"{res['cases']['positive']} |",
        f"| covered negatives | {res['coverage']['negative']} / {res['cases']['negative']} |",
        f"| implicated-hazard recall (covered positives) | {pct(res['hazard_recall'])} |",
        f"| false-alarm rate (covered negatives) | {pct(res['false_alarm_rate'])} |",
        "", "| implicated category | cases | covered | found | recall | matched negatives "
        "covered | false alarms |", "|---|---:|---:|---:|---:|---:|---:|",
    ]
    negs = res.get("negatives_by_category", {})
    for cat, d in sorted(res["by_category"].items()):
        n = negs.get(cat, {})
        lines.append(
            f"| {cat} | {d['cases']} | {d['covered']} | {d['found']} | {pct(d.get('recall'))} | "
            f"{n.get('covered', 0)} | {pct(n.get('rate'))} |")
    lines += [
        "",
        "Coverage is the honest number here. The weather slice is covered from the Iowa State "
        "ASOS archive — public historical METARs pulled for each case's airport at its snapshot "
        "(`preflight eval briefing --backfill-weather`). The wildlife, runway and lighting slices "
        "need the NOTAMs in force at the time, and live NOTAM feeds are out of scope by choice "
        "(ADR 0002), so those cases stay uncovered and are reported, not scored. Recall and "
        "false-alarm rate are computed only over covered cases.",
    ]
    return "\n".join(lines) + "\n"


def summarise(res: dict[str, Any]) -> dict[str, float | None]:
    return {"coverage_positive": res["coverage"]["positive"],
            "coverage_negative": res["coverage"]["negative"],
            "hazard_recall": res["hazard_recall"], "false_alarm_rate": res["false_alarm_rate"]}

def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = res["ran_at"].replace(":", "").replace("-", "")[:15]
    p = RUNS / f"{stamp}-{res['git_sha']}.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    RESULTS.write_text(to_markdown(res))
    summary.write("briefing", res, summarise(res), cases=res["cases"])
    return p, RESULTS
