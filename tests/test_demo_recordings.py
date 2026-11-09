"""The hosted demo replays recorded briefings; hold every recording to the live schemas.

A recording that no longer validates would render as a broken page on GitHub Pages without
any test noticing, so each event is parsed with the same models the API streams.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from preflight.schemas import Abstention, Finding

DEMO = Path(__file__).resolve().parents[1] / "demo"
RECORDINGS = sorted((DEMO / "briefings").glob("*.json"))


def test_manifest_matches_recordings() -> None:
    manifest = DEMO / "flights.json"
    if not manifest.exists():
        pytest.skip("no demo recorded yet (scripts/record_demo.py)")
    ids = {f["id"] for f in json.loads(manifest.read_text())}
    assert ids == {p.stem for p in RECORDINGS}


@pytest.mark.parametrize("path", RECORDINGS, ids=[p.stem for p in RECORDINGS])
def test_recording_matches_schemas(path: Path) -> None:
    rec = json.loads(path.read_text())
    events = rec["events"]
    assert events[-1]["event"] == "done"
    findings = [Finding.model_validate(e["data"]) for e in events if e["event"] == "finding"]
    abstentions = [
        Abstention.model_validate(e["data"]) for e in events if e["event"] == "abstention"
    ]
    done = events[-1]["data"]
    assert done["findings"] == len(findings)
    assert done["abstentions"] == len(abstentions)
    # Every claim names a source: the property the whole system is built on.
    assert all(c.citations for f in findings for c in f.claims)
