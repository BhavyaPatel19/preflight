"""Retrieval eval: metrics are pure; the golden-set builder runs against the DB on fixtures."""

import json

import pytest

from preflight.evals import retrieval as R
from preflight.retrieval.search import Hit


def _hit(ext, text="", icao=None, ordinal=0):
    return Hit(chunk_id=0, document_id=0, source="asrs", external_id=ext, title=None,
               ordinal=ordinal, text=text, icao=icao, fused_score=0.0,
               in_dense=True, in_lexical=False)


# ---------------------------------------------------------------- metrics

def test_doc_ranking_dedups_chunks_keeping_first_position():
    hits = [_hit("a", ordinal=2), _hit("b"), _hit("a", ordinal=0), _hit("c"), _hit("b", ordinal=1)]
    assert R.doc_ranking(hits) == ["a", "b", "c"]


def test_recall_at_k():
    assert R.recall_at(["x", "y", "z"], ["y"], 1) == 0.0
    assert R.recall_at(["x", "y", "z"], ["y"], 2) == 1.0
    assert R.recall_at(["x", "y", "z"], ["y", "q"], 3) == 0.5
    assert R.recall_at([], ["y"], 5) == 0.0 and R.recall_at(["y"], [], 5) == 0.0


def test_reciprocal_rank():
    assert R.reciprocal_rank(["x", "y"], ["y"], 20) == 0.5
    assert R.reciprocal_rank(["y"], ["y"], 20) == 1.0
    assert R.reciprocal_rank(["x"], ["y"], 20) == 0.0
    assert R.reciprocal_rank(["x", "y"], ["y"], 1) == 0.0          # cut-off respected


def test_ndcg_binary_single_relevant():
    assert R.ndcg_at(["y"], ["y"], 10) == pytest.approx(1.0)
    assert R.ndcg_at(["x", "y"], ["y"], 10) == pytest.approx(1 / 1.5849625)   # 1/log2(3)
    assert R.ndcg_at(["x"] * 10 + ["y"], ["y"], 10) == 0.0
    assert R.ndcg_at([], ["y"], 10) == 0.0


def test_ndcg_two_relevant_ideal_ordering_is_one():
    assert R.ndcg_at(["a", "b", "c"], ["a", "b"], 10) == pytest.approx(1.0)
    assert R.ndcg_at(["c", "a", "b"], ["a", "b"], 10) < 1.0


def test_identifier_hit_requires_airport_and_runway():
    assert R.identifier_hit(_hit("a", "cleared to land Runway 28R", icao="KSFO"), "KSFO", "28R")
    assert R.identifier_hit(_hit("a", "RWY 28R closed", icao="KSFO"), "KSFO", "28R")
    assert not R.identifier_hit(_hit("a", "Runway 28R", icao="KJFK"), "KSFO", "28R")
    assert not R.identifier_hit(_hit("a", "Runway 28L", icao="KSFO"), "KSFO", "28R")
    assert not R.identifier_hit(_hit("a", "Runway 28", icao="KSFO"), "KSFO", "28R")


def test_precision_at_10():
    hits = [_hit("a", "Runway 28R", icao="KSFO")] * 3 + [_hit("b", "nothing", icao="KSFO")] * 7
    assert R.precision_at(hits, 10, "KSFO", "28R") == pytest.approx(0.3)
    assert R.precision_at([], 10, "KSFO", "28R") == 0.0


# ---------------------------------------------------------------- golden set I/O

def test_golden_roundtrip(tmp_path):
    qs = [R.Query(kind="synopsis", id="syn-1", text="A synopsis.", relevant=("1",)),
          R.Query(kind="identifier", id="id-KSFO-28R", text="KSFO runway 28R", relevant=(),
                  icao="KSFO", runway="28R")]
    path = tmp_path / "g.jsonl"
    R.save_golden(qs, path)
    assert R.load_golden(path) == qs
    assert json.loads(path.read_text().splitlines()[0])["relevant"] == ["1"]


# ---------------------------------------------------------------- builder (db)

@pytest.mark.db
def test_build_golden_selects_eligible_reports_and_frequent_pairs(db):
    from preflight.retrieval.search import DocInput, index_documents

    class Emb:
        name, dim = "fake", 768

        def encode(self, texts, *, query=False):
            return [[0.0] * 768 for _ in texts]

    long_synopsis = "A synopsis long enough to count as a real query for the eligibility rule."
    narrative = " ".join(
        f"Sentence {i} about the approach to Runway 28R at KZZY." for i in range(120)
    )   # ~6 chunks, each mentioning the runway → (KZZY, 28R) is a frequent pair
    docs = [
        # eligible: long synopsis title, ≥ 2 chunks, has a non-synopsis chunk
        DocInput("asrs", "test-g-1", narrative + "\n\nSynopsis: " + long_synopsis,
                 title=long_synopsis, icao="KZZY"),
        # ineligible: short title
        DocInput("asrs", "test-g-2", narrative + "\n\nSynopsis: short", title="short", icao="KZZY"),
        # ineligible: single chunk
        DocInput("asrs", "test-g-3", "One sentence. Synopsis: " + long_synopsis,
                 title=long_synopsis, icao="KZZY"),
    ]
    index_documents(db, Emb(), docs)
    # Ask for everything eligible so the dev DB's real reports cannot crowd the fixtures out.
    qs = R.build_golden(db, n_synopsis=10**7, n_identifier=10**7)
    syn = {q.relevant[0] for q in qs if q.kind == "synopsis"}
    assert "test-g-1" in syn and "test-g-2" not in syn and "test-g-3" not in syn
    ident = {(q.icao, q.runway) for q in qs if q.kind == "identifier"}
    assert ("KZZY", "28R") in ident
