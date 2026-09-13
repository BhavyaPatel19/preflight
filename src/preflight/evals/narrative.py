"""Narrative evaluation: how much of what a model writes can the verifier support?

For each finding in a fixed set (NOTAM findings from the grounding fixtures,
plus live weather and delay findings for the watchlist), the model writes 1–3
sentences grounded in that finding's claims and quoted sources. Each sentence
is scored by the NLI verifier against the finding's citations. The
**unsupported-claim rate** — dropped / generated — is the model's number. Run
it per provider (``PREFLIGHT_LLM=ollama`` / ``anthropic``) for the comparison
row; the dropped sentences are listed so a reader can judge whether the
verifier was right to drop them.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from psycopg import Connection

from preflight.brief.core import delay_finding, notam_findings, weather_findings
from preflight.brief.narrate import narrate_finding
from preflight.config import settings
from preflight.db import weather as wdb
from preflight.decode.notam import parse_notam
from preflight.evals.grounding_notams import GROUNDING_NOTAMS
from preflight.llm import LLM, LLMUnavailable
from preflight.schemas import Claim, Finding
from preflight.verify.ground import _pairs_for, figures_supported
from preflight.verify.nli import Verifier

RESULTS = Path("evals/narrative/RESULTS.md")
RUNS = Path("evals/narrative/runs")


def collect_findings(
    conn: Connection[Any], *, now: datetime, max_weather: int = 10
) -> list[Finding]:
    out: list[Finding] = []
    for raw in GROUNDING_NOTAMS:
        rec = parse_notam(raw)
        out.extend(f for f in notam_findings(rec.icao or "ZZZZ", "departure", [rec])
                   if f.category != "notam")
    n_wx = 0
    for icao in settings().watchlist:
        if n_wx >= max_weather:
            break
        metar = wdb.latest(conn, icao, "METAR")
        wx, _ = weather_findings(icao, "destination", metar, None, now=now,
                                 window_start=now, window_end=now + timedelta(hours=8))
        wx = [f for f in wx if f.category == "weather"]
        d = delay_finding(conn, icao, "destination", now + timedelta(hours=3))
        if wx:
            out.extend(wx[:1])
            n_wx += 1
        if d is not None:
            out.append(d)
    return out


def run(conn: Connection[Any], llm: LLM, verifier: Verifier, *, threshold: float = 0.5,
        now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now(UTC)
    findings = collect_findings(conn, now=now)
    per_kind: dict[str, dict[str, int]] = {}
    dropped: list[dict[str, Any]] = []
    kept_examples: list[dict[str, Any]] = []
    generated = kept = failed = 0
    t0 = datetime.now(UTC)

    for f in findings:
        cits = tuple(cit for c in f.claims for cit in c.citations)
        try:
            sentences = narrate_finding(llm, f)
        except (LLMUnavailable, ValueError):
            failed += 1
            continue
        d = per_kind.setdefault(f.category, {"findings": 0, "generated": 0, "kept": 0})
        d["findings"] += 1
        for s in sentences:
            claim = Claim(text=s, citations=cits, author="llm")
            pairs = _pairs_for(f, claim)
            raw = verifier.entailment(pairs)
            score = max((sc if figures_supported(h, p) else 0.0
                         for (p, h), sc in zip(pairs, raw, strict=True)), default=0.0)
            generated += 1
            d["generated"] += 1
            if score >= threshold:
                kept += 1
                d["kept"] += 1
                if len(kept_examples) < 5:
                    kept_examples.append({"kind": f.category, "score": round(score, 3), "text": s})
            else:
                dropped.append({"kind": f.category, "score": round(score, 3), "text": s,
                                "headline": f.headline[:90]})

    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        sha = "unknown"
    seconds = (datetime.now(UTC) - t0).total_seconds()
    return {
        "ran_at": now.isoformat(timespec="seconds"), "git_sha": sha, "model": llm.name,
        "verifier": verifier.name, "threshold": threshold, "findings": len(findings),
        "failed_calls": failed, "generated": generated, "kept": kept,
        "dropped": generated - kept,
        "unsupported_rate": round((generated - kept) / generated, 3) if generated else None,
        "seconds_per_finding": round(seconds / max(1, len(findings) - failed), 1),
        "per_kind": {
            k: {**v, "unsupported_rate": (round((v["generated"] - v["kept"]) / v["generated"], 3)
                                          if v["generated"] else None)}
            for k, v in per_kind.items()
        },
        "dropped_examples": dropped[:40], "kept_examples": kept_examples,
    }


def to_markdown(res: dict[str, Any]) -> str:
    lines = [
        "# Narrative evaluation", "",
        f"Run `{res['git_sha']}` at {res['ran_at']} · model `{res['model']}` · verifier "
        f"`{res['verifier']}` at {res['threshold']} · {res['findings']} findings, "
        f"{res['seconds_per_finding']} s per finding", "",
        "| metric | value |", "|---|---:|",
        f"| sentences generated | {res['generated']} |",
        f"| kept (verifier supports them) | {res['kept']} |",
        f"| dropped | {res['dropped']} |",
        f"| **unsupported-claim rate** | **{res['unsupported_rate']}** |",
        f"| failed model calls | {res['failed_calls']} |",
        "", "| finding kind | findings | generated | kept | unsupported rate |",
        "|---|---:|---:|---:|---:|",
    ]
    for k, d in sorted(res["per_kind"].items()):
        lines.append(f"| {k} | {d['findings']} | {d['generated']} | {d['kept']} | "
                     f"{d['unsupported_rate']} |")
    lines += ["", "Kept (sample):", ""]
    lines += [f"- ({e['score']:.2f}) {e['text']}" for e in res["kept_examples"]]
    lines += ["", "Dropped — read these to judge whether the verifier was right:", ""]
    lines += [f"- ({e['score']:.2f}, {e['kind']}) {e['text']}" for e in res["dropped_examples"]]
    lines += [
        "",
        "What this measures: the share of a model's sentences the verifier cannot tie to the",
        "cited sources, on the briefing's own findings. A dropped sentence is not necessarily",
        "false — it may be interpretation the sources do not state — and in a safety-adjacent",
        "output that is the right thing to drop. Run per provider for the comparison row.",
    ]
    return "\n".join(lines) + "\n"


def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = res["ran_at"].replace(":", "").replace("-", "")[:15]
    model = res["model"].replace("/", "-").replace(":", "-")
    p = RUNS / f"{stamp}-{model}-{res['git_sha']}.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    RESULTS.parent.mkdir(parents=True, exist_ok=True)
    RESULTS.write_text(to_markdown(res))
    return p, RESULTS
