"""The CI regression gate: committed eval summaries against floors in ``evals/gates.toml``.

Two kinds of gate. *Live* suites are cheap and need no model — the injection
detector and the constructed abstention cases — so CI re-runs them and gates on
what it just measured. The rest need the retrieval, NLI or language models and
are run locally; their ``summary.json`` is committed, and the gate holds the
build to the numbers in the tree. A PR that changes retrieval without re-running
the retrieval eval will still pass — the gate is a floor under what was
measured, not proof the measurement is current — which is why every summary
carries the commit it was measured at and the gate prints it.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from preflight.evals import summary

GATES = Path("evals/gates.toml")


@dataclass(frozen=True)
class Gate:
    suite: str
    metric: str
    min: float | None = None
    max: float | None = None
    live: bool = False
    note: str = ""


@dataclass(frozen=True)
class Outcome:
    gate: Gate
    value: float | None
    ran_at: str | None
    git_sha: str | None

    @property
    def status(self) -> str:
        if self.value is None:
            return "MISSING"
        if self.gate.min is not None and self.value < self.gate.min:
            return "FAIL"
        if self.gate.max is not None and self.value > self.gate.max:
            return "FAIL"
        return "PASS"

    @property
    def bound(self) -> str:
        if self.gate.min is not None:
            return f"≥ {self.gate.min}"
        return f"≤ {self.gate.max}" if self.gate.max is not None else "—"


def load_gates(path: Path = GATES) -> list[Gate]:
    doc = tomllib.loads(path.read_text())
    gates = [Gate(**g) for g in doc.get("gate", [])]
    for g in gates:
        if g.min is None and g.max is None:
            raise ValueError(f"gate {g.suite}.{g.metric} has neither min nor max")
    return gates


def evaluate(gates: list[Gate]) -> list[Outcome]:
    out: list[Outcome] = []
    for g in gates:
        s = summary.read(g.suite)
        value = (s or {}).get("metrics", {}).get(g.metric)
        out.append(Outcome(g, value if isinstance(value, int | float) else None,
                           (s or {}).get("ran_at"), (s or {}).get("git_sha")))
    return out


def passed(outcomes: list[Outcome]) -> bool:
    return all(o.status == "PASS" for o in outcomes)


def to_markdown(outcomes: list[Outcome]) -> str:
    lines = ["| suite | metric | floor | measured | at | status |", "|---|---|---|---:|---|---|"]
    for o in outcomes:
        val = "—" if o.value is None else f"{o.value:.3f}"
        at = f"{(o.ran_at or '')[:10]} `{o.git_sha or '?'}`" if o.ran_at else "no summary"
        mark = {"PASS": "✅", "FAIL": "❌", "MISSING": "❓"}[o.status]
        lines.append(f"| {o.gate.suite} | {o.gate.metric} | {o.bound} | {val} | {at} | "
                     f"{mark} {o.status} |")
    n_fail = sum(o.status != "PASS" for o in outcomes)
    lines.append("")
    lines.append(f"**{len(outcomes) - n_fail} / {len(outcomes)} gates pass**" if n_fail == 0
                 else f"**{n_fail} gate{'s' if n_fail != 1 else ''} failing**")
    return "\n".join(lines) + "\n"


def run_live(conn_factory: Any) -> list[str]:
    """Re-run the model-free suites and refresh their summaries. Returns what ran."""
    from preflight.evals import abstention, safety

    ran: list[str] = []
    res = safety.run()
    safety.save_run(res)
    ran.append("safety")
    with conn_factory() as conn:
        ab = abstention.run(conn)
    abstention.save_run(ab)
    ran.append("abstention")
    return ran


def backfill(suites: list[str]) -> list[Path]:
    """Write summaries from the newest run file of each suite (for evals not re-run now)."""
    import importlib
    import json

    written: list[Path] = []
    for name in suites:
        runs = sorted((Path("evals") / name / "runs").glob("*.json"))
        if not runs:
            continue
        mod = importlib.import_module(f"preflight.evals.{name}")
        res = json.loads(runs[-1].read_text())
        written.append(summary.write(name, res, mod.summarise(res)))
    return written
