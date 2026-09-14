"""Precedent judge: pair building with fakes, the sheet round-trip, κ, and the summary."""

import csv

import pytest

from preflight.evals import precedent as P
from preflight.evals.precedent import JUDGE_SCHEMA, Pair, cohen_kappa
from preflight.retrieval.search import Hit


def _pair(i, source="fixture-notam", score=0.6):
    return Pair(id=f"p{i}", source=source, hazard=f"KSFO: hazard {i}", airport="KSFO",
                query="q", hit_ref=f"asrs:{i}", hit_title=None, passage=f"passage {i}",
                rerank_score=score, rank=1)


class FakeJudge:
    name = "fake-judge"

    def __init__(self, fn):
        self.fn = fn

    def complete_json(self, system, user, schema, *, max_tokens=400):
        assert schema is JUDGE_SCHEMA and "<data kind='prior-report'" in user
        return self.fn(user)


# ---------------------------------------------------------------- kappa

def test_cohen_kappa_known_values():
    assert cohen_kappa([True, True, False, False], [True, True, False, False]) == 1.0
    assert cohen_kappa([True, False, True, False], [False, True, False, True]) == -1.0
    assert cohen_kappa([True, False, True, False], [True, True, False, False]) == 0.0
    assert cohen_kappa([], []) is None
    assert cohen_kappa([True, True], [True, True]) is None          # pe == 1, undefined


# ---------------------------------------------------------------- judging

def test_judge_pair_returns_verdict_and_reason_and_survives_failures():
    j = FakeJudge(lambda u: {"relevant": True, "reason": "same phase, same error"})
    assert P.judge_pair(j, _pair(1)) == (True, "same phase, same error")

    class Down:
        name = "down"

        def complete_json(self, *a, **k):
            from preflight.llm import LLMUnavailable
            raise LLMUnavailable("off")

    verdict, reason = P.judge_pair(Down(), _pair(1))
    assert verdict is None and reason.startswith("judge failed")


# ---------------------------------------------------------------- sheet

def test_sheet_is_stratified_and_hides_the_verdict(tmp_path):
    pairs = [_pair(i, "fixture-notam", 0.8) for i in range(30)] + \
            [_pair(100 + i, "fixture-notam", 0.2) for i in range(30)] + \
            [_pair(200 + i, "ntsb-case", 0.8) for i in range(30)] + \
            [_pair(300 + i, "ntsb-case", 0.2) for i in range(30)]
    path = tmp_path / "labels.csv"
    n = P.write_sheet(pairs, n=40, path=path)
    rows = list(csv.DictReader(path.open()))
    assert n == 40 and len(rows) == 40
    assert set(rows[0]) == {"id", "hazard", "prior_report", "relevant_precedent (y/n)", "notes"}
    by_id = {p.id: p for p in pairs}
    srcs = [by_id[r["id"]].source for r in rows]
    assert 15 <= srcs.count("fixture-notam") <= 25                    # roughly balanced
    assert 15 <= sum(by_id[r["id"]].rerank_score >= 0.5 for r in rows) <= 25


def test_read_sheet_accepts_y_n_variants_and_ignores_blank(tmp_path):
    path = tmp_path / "labels.csv"
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "hazard", "prior_report", "relevant_precedent (y/n)", "notes"])
        w.writerows([["a", "", "", "y", ""], ["b", "", "", "No", ""], ["c", "", "", "", ""],
                     ["d", "", "", "1", "sure"]])
    assert P.read_sheet(path) == {"a": True, "b": False, "d": True}


# ---------------------------------------------------------------- summary

def test_summary_without_labels_is_marked_unvalidated():
    pairs = [_pair(1, score=0.9), _pair(2, score=0.6), _pair(3, score=0.2), _pair(4, score=0.1)]
    verdicts = {"p1": {"relevant": True}, "p2": {"relevant": False},
                "p3": {"relevant": False}, "p4": {"relevant": None}}
    res = P.summarize(pairs, verdicts, {}, model="fake", threshold=0.5)
    assert res["judged"] == 3 and res["attached"] == {"n": 2, "judge_relevant": 0.5}
    assert res["human"] == {"labelled": 0}
    md = P.to_markdown(res)
    assert "unvalidated until the sheet is filled" in md and "Cohen" not in md


def test_summary_with_labels_reports_kappa_and_attached_precision():
    pairs = [_pair(i, score=0.9 if i % 2 else 0.2) for i in range(1, 9)]
    verdicts = {p.id: {"relevant": i % 2 == 1} for i, p in enumerate(pairs, start=1)}
    labels = {p.id: i % 2 == 1 for i, p in enumerate(pairs, start=1)}   # human agrees fully
    labels["p2"] = True                                                  # except one
    res = P.summarize(pairs, verdicts, labels, model="fake", threshold=0.5)
    h = res["human"]
    assert h["n_overlap"] == 8 and h["agreement"] == 0.875 and 0.5 < h["kappa"] < 1.0
    assert h["attached_precision_human"] == 1.0          # every attached pair was relevant
    assert "Cohen's κ" in P.to_markdown(res)


# ---------------------------------------------------------------- pair building (fakes)

@pytest.mark.db
def test_build_pairs_uses_search_and_rewrites(db, monkeypatch):
    class R:
        def __init__(self):
            self.queries = []

        def search(self, conn, q, **kw):
            self.queries.append(q)
            return [Hit(chunk_id=0, document_id=0, source="asrs", external_id="9", title="t",
                        ordinal=0, text="a passage", icao=None, fused_score=0.0,
                        in_dense=True, in_lexical=False, rerank_score=0.7)]

    class LLM:
        name = "fake"

        def complete_json(self, system, user, schema, *, max_tokens=400):
            return {"query": "operational consequence query text"}

    monkeypatch.setattr(P, "load_cases", lambda: [])          # fixtures only, no golden file dep
    r = R()
    pairs = P.build_pairs(db, r, LLM(), n_cases=0, k=1)
    assert pairs and all(p.source == "fixture-notam" for p in pairs)
    assert all(q == "operational consequence query text" for q in r.queries)
    assert pairs[0].hit_ref == "asrs:9" and pairs[0].rerank_score == 0.7
    ids = [p.id for p in pairs]
    assert len(ids) == len(set(ids))
