"""Entity extraction eval: the rule decoder and the fine-tuned model on the same gold set.

Scoring is per entity type, precision / recall / F1, with a prediction counted
correct when its type matches and its span overlaps an unmatched gold span of
that type (the rule decoder marks identifiers, the gold marks whole mentions;
overlap is the fair common ground). Exact-span F1 is reported beside it. The
red-team items add a third number: entities predicted inside injected prose,
where the gold has none — a model that tags "the runway is open" has been led.

Two data sets, never blended: the **gold** set (real-format, hand-labelled) is
the number that matters; the **synthetic** validation split says how well the
model learned its training distribution and nothing more.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from preflight.decode.notam import extract_entities
from preflight.evals import summary
from preflight.extract import gold as gold_mod
from preflight.extract.labels import TYPES, Span

RESULTS = Path("evals/extraction/RESULTS.md")
RUNS = Path("evals/extraction/runs")
ENTITY_TYPES = tuple(t for t in TYPES if t != "TIME")

Predictor = Callable[[str], list[Span]]


def predict_rules(text: str) -> list[Span]:
    """The Sprint 1 rule decoder, as a predictor over a body. It does not tag TIME."""
    out: list[Span] = []
    for e in extract_entities(text):
        if e.span is not None:
            out.append(Span(e.span[0], e.span[1], e.type.value))
    return out


def _match(pred: Sequence[Span], gold: Sequence[Span], *, exact: bool) -> int:
    """Greedy one-to-one matching by type; returns the number of correct predictions."""
    used: set[int] = set()
    hits = 0
    for p in sorted(pred, key=lambda s: s.start):
        for j, g in enumerate(gold):
            if j in used or g.type != p.type:
                continue
            ok = (p.start, p.end) == (g.start, g.end) if exact else p.overlaps(g)
            if ok:
                used.add(j)
                hits += 1
                break
    return hits


def score(rows: Sequence[dict[str, Any]], predictor: Predictor) -> dict[str, Any]:
    per: dict[str, dict[str, int]] = {t: {"tp": 0, "fp": 0, "fn": 0, "tp_exact": 0}
                                      for t in TYPES}
    prose_fp = 0
    for r in rows:
        text = str(r["text"])
        gold = [Span(int(a), int(b), str(t)) for a, b, t in r["spans"]]
        pred = predictor(text)
        for t in TYPES:
            g_t = [g for g in gold if g.type == t]
            p_t = [p for p in pred if p.type == t]
            tp = _match(p_t, g_t, exact=False)
            per[t]["tp"] += tp
            per[t]["fp"] += len(p_t) - tp
            per[t]["fn"] += len(g_t) - tp
            per[t]["tp_exact"] += _match(p_t, g_t, exact=True)
        if r.get("source") == "red-team":
            prose_fp += sum(1 for p in pred if not any(p.overlaps(g) for g in gold))

    def prf(d: dict[str, int], tp_key: str = "tp") -> dict[str, float | None]:
        tp, fp, fn = d[tp_key], d["fp"] + (d["tp"] - d[tp_key]), d["fn"] + (d["tp"] - d[tp_key])
        p = tp / (tp + fp) if tp + fp else None
        rc = tp / (tp + fn) if tp + fn else None
        f = 2 * p * rc / (p + rc) if p and rc else (0.0 if (tp + fp + fn) else None)
        return {"precision": p, "recall": rc, "f1": f, "support": d["tp"] + d["fn"]}

    by_type = {t: prf(per[t]) for t in TYPES}
    by_type_exact = {t: prf(per[t], "tp_exact") for t in TYPES}
    ent_f1 = [by_type[t]["f1"] for t in ENTITY_TYPES if by_type[t]["support"]]
    ent_f1_exact = [by_type_exact[t]["f1"] for t in ENTITY_TYPES if by_type_exact[t]["support"]]
    return {
        "items": len(rows),
        "macro_f1_entities": round(sum(f for f in ent_f1 if f is not None) / len(ent_f1), 4)
        if ent_f1 else None,
        "macro_f1_entities_exact": round(
            sum(f for f in ent_f1_exact if f is not None) / len(ent_f1_exact), 4)
        if ent_f1_exact else None,
        "time_f1": by_type["TIME"]["f1"],
        "by_type": by_type,
        "prose_false_positives": prose_fp,
    }


def run(predictors: dict[str, Predictor], *, synthetic_val: Path | None = None) -> dict[str, Any]:
    gold_rows = gold_mod.load()
    res: dict[str, Any] = {
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"), "git_sha": _git_sha(),
        "gold_items": len(gold_rows),
        "gold_entities": sum(len(spans) for r in gold_rows for spans in [r["spans"]]
                             if isinstance(spans, list)),
        "systems": {},
    }
    val_rows = None
    if synthetic_val and synthetic_val.exists():
        val_rows = [json.loads(line) for line in synthetic_val.read_text().splitlines()
                    if line.strip()]
        res["synthetic_items"] = len(val_rows)
    for name, pred in predictors.items():
        entry: dict[str, Any] = {"gold": score(gold_rows, pred)}
        if val_rows is not None:
            entry["synthetic"] = score(val_rows, pred)
        res["systems"][name] = entry
    return res


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _f(x: float | None) -> str:
    return "—" if x is None else f"{x:.3f}"


def to_markdown(res: dict[str, Any]) -> str:
    lines = [
        "# Entity extraction evaluation", "",
        f"Run `{res['git_sha']}` at {res['ran_at']} · gold: {res['gold_items']} real-format "
        f"NOTAM bodies, {res['gold_entities']} entity mentions, hand-labelled "
        "(`evals/extraction/gold.jsonl`)"
        + (f" · synthetic validation: {res['synthetic_items']} generated bodies"
           if res.get("synthetic_items") else ""), "",
        "| system | data | macro-F1 (8 entity types, overlap) | macro-F1 (exact span) | "
        "TIME F1 | entities tagged in injected prose |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for name, entry in res["systems"].items():
        for data, sc in entry.items():
            lines.append(
                f"| {name} | {data} | {_f(sc['macro_f1_entities'])} | "
                f"{_f(sc['macro_f1_entities_exact'])} | {_f(sc['time_f1'])} | "
                f"{sc['prose_false_positives'] if data == 'gold' else '—'} |")
    lines += ["", "**Per type on the gold set** (overlap match; P / R / F1 · support):", "",
              "| type | " + " | ".join(res["systems"]) + " |",
              "|---|" + "---:|" * len(res["systems"])]
    for t in TYPES:
        cells = []
        for entry in res["systems"].values():
            d = entry["gold"]["by_type"][t]
            cells.append(f"{_f(d['precision'])} / {_f(d['recall'])} / {_f(d['f1'])} · "
                         f"{d['support']}")
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    lines += [
        "",
        "The gold set is the number that counts: real formats, hand labels, and 60 items whose "
        "prose is an attack on the reader. The synthetic column says only how well a system fits "
        "the generator's distribution. The rule decoder marks identifiers rather than whole "
        "mentions and does not tag TIME, which is what the overlap/exact split and the TIME "
        "column show. No real FAA NOTAM is in either set (ADR 0002).",
    ]
    return "\n".join(lines) + "\n"


def summarise(res: dict[str, Any]) -> dict[str, float | None]:
    out: dict[str, float | None] = {}
    for name, entry in res["systems"].items():
        key = name.replace("-", "_").replace(" ", "_")
        out[f"{key}_gold_macro_f1"] = entry["gold"]["macro_f1_entities"]
        out[f"{key}_gold_prose_fp"] = entry["gold"]["prose_false_positives"]
        if "synthetic" in entry:
            out[f"{key}_synthetic_macro_f1"] = entry["synthetic"]["macro_f1_entities"]
    return out


def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = res["ran_at"].replace(":", "").replace("-", "")[:15]
    p = RUNS / f"{stamp}-{res['git_sha']}.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    RESULTS.write_text(to_markdown(res))
    summary.write("extraction", res, summarise(res), gold_items=res["gold_items"])
    return p, RESULTS
