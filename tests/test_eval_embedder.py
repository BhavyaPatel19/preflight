"""Embedder ablation: subset construction and in-memory scoring, with a fake model."""

import pytest

from preflight.evals import embedder as EM
from preflight.evals.retrieval import Query


def test_markdown_reports_delta_against_the_first_model():
    res = {"ran_at": "t", "git_sha": "abc", "queries": 2, "passages": 10, "target_reports": 2,
           "models": [
               {"model": "a", "dim": 8, "recall_at_5": 0.5, "recall_at_10": 0.5,
                "recall_at_20": 0.5, "ndcg_at_10": 0.4, "embed_seconds": 1.0,
                "chunks_per_second": 10.0},
               {"model": "b", "dim": 16, "recall_at_5": 0.5, "recall_at_10": 0.75,
                "recall_at_20": 1.0, "ndcg_at_10": 0.6, "embed_seconds": 2.0,
                "chunks_per_second": 5.0}]}
    md = EM.to_markdown(res)
    assert "| `b` | 16 | 0.500 | 0.750 | 1.000 | 0.600 | +0.500 | 5.0 |" in md
    assert "not comparable" in md


def test_score_model_ranks_by_cosine_and_dedups_documents(monkeypatch):
    """A fake embedder that maps a keyword to a one-hot vector; the target report's chunks share
    the query's keyword, so it must rank first and be counted once."""
    pytest.importorskip("numpy")          # ships with the ML extras; absent in CI
    import preflight.retrieval.embed as embed_mod

    class Fake:
        def __init__(self, model, batch_size=32):
            self.name = model

        def encode(self, texts, *, query=False):
            vocab = ["alpha", "beta", "gamma"]
            out = []
            for t in texts:
                v = [1.0 if w in t else 0.0 for w in vocab]
                n = sum(v) ** 0.5 or 1.0
                out.append([x / n for x in v])
            return out

    monkeypatch.setattr(embed_mod, "STEmbedder", Fake)
    passages = [EM.Passage("R1", "alpha chunk one"), EM.Passage("R1", "alpha chunk two"),
                EM.Passage("R2", "beta"), EM.Passage("R3", "gamma")]
    queries = [Query(kind="synopsis", id="q1", text="alpha", relevant=("R1",)),
               Query(kind="synopsis", id="q2", text="gamma", relevant=("R3",)),
               Query(kind="synopsis", id="q3", text="nothing", relevant=("R2",))]
    res = EM.score_model("fake", queries, passages)
    assert res["dim"] == 3 and res["recall_at_20"] == pytest.approx(1.0)
    # q1 and q2 rank their report first (R1's two chunks count once); q3 matches nothing, so
    # R2 lands behind the tied zero-score chunks and nDCG falls short of 1.
    assert 0.8 < res["ndcg_at_10"] < 1.0


@pytest.mark.db
def test_subset_holds_every_target_narrative_chunk(db):
    from preflight.retrieval.search import index_document
    from tests.test_retrieval import HashEmbedder

    emb = HashEmbedder()
    body = "\n\n".join(f"Paragraph {i}. " + "The crew taxied toward the runway. " * 40
                        for i in range(4))
    index_document(db, emb, source="asrs", external_id="T-1", icao=None,
                   text="Synopsis: a summary.\n\n" + body, metadata={})
    index_document(db, emb, source="asrs", external_id="T-2", icao=None, text=body, metadata={})
    qs = [Query(kind="synopsis", id="q", text="x", relevant=("T-1",))]
    sub = EM.build_subset(db, qs, size=5)
    ids = [p.external_id for p in sub]
    assert "T-1" in ids and all("Synopsis:" not in p.text for p in sub if p.external_id == "T-1")
    assert len(sub) <= max(5, ids.count("T-1"))
