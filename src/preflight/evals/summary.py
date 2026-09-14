"""One small committed file per eval, so the CI gate can read numbers without models.

Full runs live in ``evals/<suite>/runs/`` and are ignored by git (they carry
per-query detail and change on every run). ``evals/<suite>/summary.json`` is
the headline metrics of the latest run, with the commit and time it was
measured at, and is committed: it is what ``preflight eval gate`` compares
against ``evals/gates.toml``, and what a reviewer diffs when a PR moves a number.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

EVALS = Path("evals")


def path_for(suite: str) -> Path:
    return EVALS / suite / "summary.json"


def write(suite: str, res: dict[str, Any], metrics: dict[str, float | None],
          **extra: Any) -> Path:
    """Write the suite's summary from a finished run's result dict."""
    doc = {
        "suite": suite,
        "ran_at": res.get("ran_at") or res.get("generated_at")
        or datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": res.get("git_sha"),
        "metrics": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in metrics.items()},
        **extra,
    }
    p = path_for(suite)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2) + "\n")
    return p


def read(suite: str) -> dict[str, Any] | None:
    p = path_for(suite)
    return json.loads(p.read_text()) if p.exists() else None
