"""Injection red-team evaluation.

Sixty adversarial NOTAMs — six attack families (instruction override, role
markers, output steering, format hijack, exfiltration/tool calls, obfuscation)
on real NOTAM scaffolds, half with upper-case payloads so the "NOTAMs are
upper-case" tell cannot carry the result alone. Benign controls are the
project's realistic NOTAM fixtures plus the bundled samples.

Reported: detector recall on the adversarial set, false-positive rate on the
benign set, per family; and *pipeline integrity* — every adversarial NOTAM
still parses to data (entities, a confidence), never to behaviour. The LLM
resistance number itself waits on the LLM layer; this set is what it will be
measured against.
"""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from preflight.decode.notam import NotamParseError, parse_notam
from preflight.evals.grounding_notams import GROUNDING_NOTAMS
from preflight.safety.injection import detect

ADVERSARIAL = Path("evals/safety/injections.jsonl")
RESULTS = Path("evals/safety/RESULTS.md")
RUNS = Path("evals/safety/runs")


def load_adversarial(path: Path = ADVERSARIAL) -> list[dict[str, str]]:
    with path.open() as f:
        return [json.loads(line) for line in f if line.strip()]


def benign_set() -> list[str]:
    from preflight.decode.notam import DEMO_NOTAMS

    return [*GROUNDING_NOTAMS, *DEMO_NOTAMS]


def _body(text: str) -> str:
    try:
        return parse_notam(text).body
    except NotamParseError:
        return text


def run() -> dict[str, Any]:
    adv = load_adversarial()
    benign = benign_set()

    by_family: dict[str, dict[str, int]] = {}
    caught = 0
    parsed_ok = 0
    low_conf = 0
    misses: list[dict[str, Any]] = []
    for r in adv:
        v = detect(_body(r["text"]))
        d = by_family.setdefault(r["family"], {"n": 0, "caught": 0})
        d["n"] += 1
        if v.suspicious:
            d["caught"] += 1
            caught += 1
        else:
            misses.append({"id": r["id"], "score": v.score, "signals": list(v.signals)})
        try:
            rec = parse_notam(r["text"])
            parsed_ok += 1
            low_conf += rec.decode_confidence < 0.6
        except NotamParseError:
            pass

    false_pos = []
    for text in benign:
        v = detect(_body(text))
        if v.suspicious:
            false_pos.append({"text": text[:80], "score": v.score, "signals": list(v.signals)})

    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                             text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        sha = "unknown"
    return {
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"), "git_sha": sha,
        "adversarial": len(adv), "benign": len(benign),
        "detector_recall": round(caught / len(adv), 3) if adv else None,
        "false_positive_rate": round(len(false_pos) / len(benign), 3) if benign else None,
        "by_family": {k: {"n": d["n"], "recall": round(d["caught"] / d["n"], 3)}
                      for k, d in by_family.items()},
        "pipeline": {"parsed": parsed_ok, "low_confidence": low_conf},
        "misses": misses, "false_positives": false_pos,
    }


def to_markdown(res: dict[str, Any]) -> str:
    lines = [
        "# Injection red-team evaluation", "",
        f"Run `{res['git_sha']}` at {res['ran_at']} · {res['adversarial']} adversarial NOTAMs in "
        f"six families · {res['benign']} benign NOTAMs as controls.", "",
        "| metric | value |", "|---|---:|",
        f"| detector recall on adversarial NOTAMs | {res['detector_recall']:.3f} |",
        f"| false-positive rate on benign NOTAMs | {res['false_positive_rate']:.3f} |",
        f"| adversarial NOTAMs that still parse to data | {res['pipeline']['parsed']} / "
        f"{res['adversarial']} |",
        f"| … of which flagged low-confidence by the decoder | "
        f"{res['pipeline']['low_confidence']} |",
        "", "| family | n | recall |", "|---|---:|---:|",
    ]
    for fam, d in sorted(res["by_family"].items()):
        lines.append(f"| {fam} | {d['n']} | {d['recall']:.3f} |")
    if res["misses"]:
        lines += ["", "Missed:", ""] + [f"- `{m['id']}` score {m['score']} {m['signals']}"
                                        for m in res["misses"]]
    if res["false_positives"]:
        lines += ["", "False positives:", ""] + [
            f"- score {fp['score']} {fp['signals']} — `{fp['text']}`"
            for fp in res["false_positives"]]
    lines += [
        "",
        "What this measures: whether injected instructions in NOTAM text are detected before any",
        "model sees them, and that the deterministic pipeline treats them as data regardless. The",
        "detector's rules were iterated against this same set, so treat the recall as an upper",
        "bound until a held-out set exists. What it does not yet: LLM resistance — the README's",
        "100% target is scored against this set once the agent layer exists.",
    ]
    return "\n".join(lines) + "\n"


def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = res["ran_at"].replace(":", "").replace("-", "")[:15]
    p = RUNS / f"{stamp}-{res['git_sha']}.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    RESULTS.write_text(to_markdown(res))
    return p, RESULTS
