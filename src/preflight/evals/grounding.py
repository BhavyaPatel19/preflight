"""Grounding evaluation: does the verifier accept true claims and reject corrupted ones?

Claims come from real briefing machinery — NOTAM findings from a fixture set
of realistic NOTAMs, weather and delay findings from whatever the database
holds for the watchlist. Each true claim is then *corrupted* in one material
way — a runway designator flipped, closed made open, a wind speed or delay
changed, a validity time shifted — with the citation left untouched. A good
verifier accepts the originals and rejects the corruptions.

Two rates, reported per claim kind and across thresholds:
  true-claim acceptance   (a low value hides real hazards behind ✗ marks)
  corruption rejection    (a low value lets fabricated details through)
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg import Connection

from preflight.brief.core import delay_finding, notam_findings, weather_findings
from preflight.config import settings
from preflight.db import weather as wdb
from preflight.decode.notam import parse_notam
from preflight.schemas import Claim, Finding
from preflight.verify.ground import _pairs_for, figures_supported
from preflight.verify.nli import Verifier

RESULTS = Path("evals/grounding/RESULTS.md")
RUNS = Path("evals/grounding/runs")
THRESHOLDS = (0.3, 0.5, 0.7)


@dataclass(frozen=True)
class Item:
    kind: str                    # notam | weather | delay
    finding: Finding
    claim: Claim
    corrupted_text: str
    corruption: str


# --------------------------------------------------------------------------
# Corruptions: one material change per claim, chosen by what the claim contains
# --------------------------------------------------------------------------

_RWY = re.compile(r"\b(\d{1,2})([LRC])\b")
_RWY_NOSIDE = re.compile(r"\bRunway (\d{1,2})\b(?![LRC])")
_TIME = re.compile(r"\b(\d{2}) (\w{3}) (\d{2})(\d{2})Z\b")
_WIND = re.compile(r"wind (\d{3})/(\d+)")
_VIS = re.compile(r"vis ([\d.]+) SM")
_CEIL = re.compile(r"ceiling (\d+) ft")
_MEDIAN = re.compile(r"median arrival delay at (\w{4}) was (-?\d+) min")


def corrupt(text: str) -> tuple[str, str] | None:
    """(corrupted text, what changed), or None if nothing material could be changed."""
    if " closed" in text:
        return text.replace(" closed", " open", 1), "closed→open"
    if "unserviceable" in text:
        return text.replace("unserviceable", "serviceable", 1), "unserviceable→serviceable"
    if m := _RWY.search(text):
        side = {"L": "R", "R": "L", "C": "L"}[m.group(2)]
        return text[:m.start(2)] + side + text[m.end(2):], f"runway side {m.group(2)}→{side}"
    if m := _RWY_NOSIDE.search(text):
        n = (int(m.group(1)) + 9) % 36 or 36
        return text[:m.start(1)] + str(n) + text[m.end(1):], f"runway {m.group(1)}→{n}"
    if m := _WIND.search(text):
        kt = int(m.group(2)) + 18
        return text[:m.start(2)] + str(kt) + text[m.end(2):], f"wind {m.group(2)}→{kt} kt"
    if m := _CEIL.search(text):
        return text[:m.start(1)] + "200" + text[m.end(1):], f"ceiling {m.group(1)}→200 ft"
    if m := _VIS.search(text):
        return text[:m.start(1)] + "0.5" + text[m.end(1):], f"vis {m.group(1)}→0.5 SM"
    if m := _MEDIAN.search(text):
        v = int(m.group(2)) + 45
        return text[:m.start(2)] + str(v) + text[m.end(2):], f"median {m.group(2)}→{v} min"
    if m := _TIME.search(text):
        hh = (int(m.group(3)) + 6) % 24
        return text[:m.start(3)] + f"{hh:02d}" + text[m.end(3):], f"time {m.group(3)}→{hh:02d}Z"
    return None


# --------------------------------------------------------------------------
# Item collection
# --------------------------------------------------------------------------

def collect_items(conn: Connection[Any], notam_texts: list[str], *, now: datetime) -> list[Item]:
    items: list[Item] = []

    for raw in notam_texts:
        rec = parse_notam(raw)
        for f in notam_findings(rec.icao or "ZZZZ", "departure", [rec]):
            if f.category == "notam":
                continue
            for c in f.claims:
                if (cr := corrupt(c.text)) and _pairs_for(f, c):
                    items.append(Item("notam", f, c, cr[0], cr[1]))

    for icao in settings().watchlist:
        metar = wdb.latest(conn, icao, "METAR")
        taf = wdb.latest(conn, icao, "TAF")
        wx, _ = weather_findings(icao, "destination", metar, taf, now=now,
                                 window_start=now, window_end=now + timedelta(hours=8))
        for f in wx:
            if f.category != "weather":
                continue
            for c in f.claims:
                if (cr := corrupt(c.text)) and _pairs_for(f, c):
                    items.append(Item("weather", f, c, cr[0], cr[1]))
        d = delay_finding(conn, icao, "destination", now + timedelta(hours=3))
        if d is not None:
            for c in d.claims:
                if (cr := corrupt(c.text)) and _pairs_for(d, c):
                    items.append(Item("delay", d, c, cr[0], cr[1]))
    return items


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------

def run(conn: Connection[Any], verifier: Verifier, notam_texts: list[str],
        *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    items = collect_items(conn, notam_texts, now=now)

    pairs: list[tuple[str, str]] = []
    index: list[tuple[int, bool, int]] = []          # (item, is_true, n_pairs)
    for i, it in enumerate(items):
        true_pairs = _pairs_for(it.finding, it.claim)
        corrupt_pairs = [(p, it.corrupted_text) for p, _ in true_pairs]
        pairs.extend(true_pairs)
        index.append((i, True, len(true_pairs)))
        pairs.extend(corrupt_pairs)
        index.append((i, False, len(corrupt_pairs)))
    scores = verifier.entailment(pairs)

    best: dict[tuple[int, bool], float] = {}
    k = 0
    for i, is_true, n in index:
        gated = [sc if figures_supported(h, p) else 0.0
                 for (p, h), sc in zip(pairs[k:k + n], scores[k:k + n], strict=True)]
        best[(i, is_true)] = max(gated) if n else 0.0
        k += n

    by_kind: dict[str, dict[str, Any]] = {}
    for thr in THRESHOLDS:
        for i, it in enumerate(items):
            d = by_kind.setdefault(it.kind, {}).setdefault(str(thr), {"n": 0, "tar": 0, "crr": 0})
            d["n"] += 1
            d["tar"] += best[(i, True)] >= thr
            d["crr"] += best[(i, False)] < thr
    table: dict[str, dict[str, dict[str, float | int]]] = {}
    for kind, per_thr in by_kind.items():
        table[kind] = {thr: {"n": d["n"], "true_accept": round(d["tar"] / d["n"], 3),
                             "corrupt_reject": round(d["crr"] / d["n"], 3)}
                       for thr, d in per_thr.items()}
    n = len(items)
    def rate(pred: Any) -> float | None:
        return round(sum(pred(i) for i in range(n)) / n, 3) if n else None

    overall = {str(thr): {
        "true_accept": rate(lambda i, t=thr: best[(i, True)] >= t),
        "corrupt_reject": rate(lambda i, t=thr: best[(i, False)] < t),
    } for thr in THRESHOLDS}

    misses = [{"kind": it.kind, "claim": it.claim.text[:120], "corruption": it.corruption,
               "true_score": round(best[(i, True)], 3), "corrupt_score": round(best[(i, False)], 3)}
              for i, it in enumerate(items)
              if best[(i, True)] < 0.5 or best[(i, False)] >= 0.5]

    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        sha = "unknown"
    return {"ran_at": datetime.now(UTC).isoformat(timespec="seconds"), "git_sha": sha,
            "model": verifier.name, "items": n, "by_kind": table, "overall": overall,
            "misses_at_0.5": misses}


def to_markdown(res: dict[str, Any]) -> str:
    lines = [
        "# Grounding evaluation", "",
        f"Run `{res['git_sha']}` at {res['ran_at']} · verifier `{res['model']}` · {res['items']} "
        "true claims, each paired with one materially corrupted copy (citation unchanged).", "",
        "| threshold | true-claim acceptance ↑ | corruption rejection ↑ |", "|---|---:|---:|",
    ]
    for thr, d in res["overall"].items():
        lines.append(f"| {thr} | {d['true_accept']:.3f} | {d['corrupt_reject']:.3f} |")
    lines += ["", "Per claim kind at the production threshold (0.5):", "",
              "| kind | n | true-claim acceptance | corruption rejection |", "|---|---:|---:|---:|"]
    for kind, per in sorted(res["by_kind"].items()):
        d = per["0.5"]
        lines.append(f"| {kind} | {d['n']} | {d['true_accept']:.3f} | {d['corrupt_reject']:.3f} |")
    if res["misses_at_0.5"]:
        lines += ["", "Misses at 0.5 (true claim scored < 0.5, or corrupted claim ≥ 0.5):", "",
                  "| kind | corruption | true | corrupt | claim |", "|---|---|---:|---:|---|"]
        for m in res["misses_at_0.5"][:25]:
            lines.append(f"| {m['kind']} | {m['corruption']} | {m['true_score']:.2f} | "
                         f"{m['corrupt_score']:.2f} | {m['claim'][:80]} |")
    lines += [
        "",
        "What this measures: whether the NLI verifier can tell a claim the citation supports",
        "from one it does not, on the briefing's own phrasing. What it does not: LLM-written",
        "prose — that arrives with the agent layer, and this harness is what will gate it.",
    ]
    return "\n".join(lines) + "\n"


def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = res["ran_at"].replace(":", "").replace("-", "")[:15]
    p = RUNS / f"{stamp}-{res['git_sha']}.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    RESULTS.write_text(to_markdown(res))
    return p, RESULTS
