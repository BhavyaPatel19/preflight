"""The regression gate: floors from TOML, summaries on disk, pass/fail/missing."""

import json
from pathlib import Path

import pytest

from preflight.evals import gate as G
from preflight.evals import summary


@pytest.fixture
def evals_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(summary, "EVALS", tmp_path)
    return tmp_path


def _toml(tmp_path, text):
    p = tmp_path / "gates.toml"
    p.write_text(text)
    return p


def test_committed_gates_file_is_valid_and_every_gate_has_a_bound():
    gates = G.load_gates()
    assert gates and all((g.min is not None) != (g.max is not None) for g in gates)
    assert {g.suite for g in gates if g.live} == {"safety", "abstention", "extraction"}


def test_min_max_and_missing(evals_dir):
    summary.write("a", {"ran_at": "2026-09-14T00:00:00", "git_sha": "abc"},
                  {"score": 0.8, "err": 0.1})
    gates = G.load_gates(_toml(evals_dir, '''
[[gate]]
suite = "a"
metric = "score"
min = 0.7
[[gate]]
suite = "a"
metric = "err"
max = 0.05
[[gate]]
suite = "a"
metric = "absent"
min = 0.1
[[gate]]
suite = "never-run"
metric = "x"
min = 0.0
'''))
    out = G.evaluate(gates)
    assert [o.status for o in out] == ["PASS", "FAIL", "MISSING", "MISSING"]
    assert not G.passed(out)
    md = G.to_markdown(out)
    assert "❌ FAIL" in md and "❓ MISSING" in md and "3 gates failing" in md
    assert "`abc`" in md and "no summary" in md


def test_gate_without_a_bound_is_rejected(evals_dir):
    with pytest.raises(ValueError, match="neither min nor max"):
        G.load_gates(_toml(evals_dir, '[[gate]]\nsuite = "a"\nmetric = "m"\n'))


def test_summary_rounds_and_records_provenance(evals_dir):
    p = summary.write("s", {"ran_at": "t", "git_sha": "deadbee"}, {"m": 0.123456, "n": 3},
                      model="x")
    doc = json.loads(Path(p).read_text())
    assert doc == {"suite": "s", "ran_at": "t", "git_sha": "deadbee",
                   "metrics": {"m": 0.1235, "n": 3}, "model": "x"}
    assert summary.read("s") == doc and summary.read("nope") is None


def test_every_summarise_reads_its_suites_shape():
    """The summarisers are the contract between run files and the gate; exercise each."""
    from preflight.evals import (
        abstention,
        briefing,
        forecast,
        grounding,
        narrative,
        precedent,
        retrieval,
        safety,
    )

    assert retrieval.summarise({"configs": {"hybrid+rerank": {"ndcg_at_10": 0.4}},
                                "rerank_lift_ndcg_at_10": 0.09})["hybrid_rerank_ndcg_at_10"] == 0.4
    assert forecast.summarise({"summary": {"chronos-bolt": {"mase": 0.7}}})["chronos_mase"] == 0.7
    assert grounding.summarise({"overall": {"0.5": {"true_accept": 1.0, "corrupt_reject": 0.9}}}
                               )["corrupt_reject"] == 0.9
    assert safety.summarise({"detector_recall": 1.0, "false_positive_rate": 0.0}
                            )["detector_recall"] == 1.0
    assert narrative.summarise({"unsupported_rate": 0.01, "generated": 9, "failed_calls": 0}
                               )["unsupported_rate"] == 0.01
    assert precedent.summarise({"attached": {"judge_relevant": 0.7}, "human": {}}
                               )["cohen_kappa"] is None
    assert briefing.summarise({"coverage": {"positive": 0, "negative": 0}, "hazard_recall": None,
                               "false_alarm_rate": None})["coverage_positive"] == 0
    assert abstention.summarise({"recall": 1.0, "false_abstention_rate": 0.0})["recall"] == 1.0
