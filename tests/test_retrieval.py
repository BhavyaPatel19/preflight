"""Hybrid retrieval against the real database with fake models (no torch in CI)."""

import hashlib
import math

import pytest

from preflight.db import corpus
from preflight.retrieval.embed import Embedder, Reranker
from preflight.retrieval.search import Retriever, index_document
from tests.fixtures_corpus import SYNTHETIC_NOTES

DIM = 768


class HashEmbedder:
    """Deterministic bag-of-words hashing → similarity tracks term overlap."""

    name = "fake-hash-768"
    dim = DIM

    def encode(self, texts, *, query=False):
        out = []
        for t in texts:
            v = [0.0] * DIM
            for tok in t.lower().split():
                tok = tok.strip(".,;:()")
                if tok:
                    v[int(hashlib.md5(tok.encode()).hexdigest(), 16) % DIM] += 1.0
            n = math.sqrt(sum(x * x for x in v)) or 1.0
            out.append([x / n for x in v])
        return out


class SubstringReranker:
    name = "fake-substring"

    def __init__(self, needle):
        self.needle = needle

    def score(self, query, texts):
        return [1.0 if self.needle in t else 0.0 for t in texts]


def mine(hits):
    """Only this suite's documents, so anything else in the dev DB cannot affect ranking."""
    return [h for h in hits if h.external_id.startswith("test-syn-")]


def test_fakes_satisfy_protocols():
    assert isinstance(HashEmbedder(), Embedder) and isinstance(SubstringReranker("x"), Reranker)


def test_lexical_query_is_or_joined_and_sanitised():
    assert corpus.lexical_query("Runway 28R closed! (WIP)") == "28r | closed | runway | wip"
    assert corpus.lexical_query("a b") == ""                 # single chars dropped


# ---------------------------------------------------------------- db

@pytest.fixture
def indexed(db):
    emb = HashEmbedder()
    for ext, (icao, text) in SYNTHETIC_NOTES.items():
        index_document(db, emb, source="ops_note", external_id=f"test-{ext}", text=text,
                       icao=icao, metadata={"synthetic": True})
    return db


@pytest.mark.db
def test_index_document_chunks_and_embeds(indexed):
    n = indexed.execute(
        "SELECT count(*), count(embedding), min(embedding_model) FROM chunks c "
        "JOIN documents d ON d.id = c.document_id WHERE d.external_id LIKE 'test-syn-%'"
    ).fetchone()
    assert n == (5, 5, "fake-hash-768")


@pytest.mark.db
def test_reindex_replaces_chunks(indexed):
    emb = HashEmbedder()
    index_document(indexed, emb, source="ops_note", external_id="test-syn-001", text="Replaced.")
    rows = indexed.execute(
        "SELECT c.text FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.external_id = 'test-syn-001'"
    ).fetchall()
    assert rows == [("Replaced.",)]


@pytest.mark.db
def test_lexical_mode_finds_exact_identifier(indexed):
    r = Retriever(HashEmbedder())
    hits = mine(r.search(indexed, "28L closed", mode="lexical", rerank=False, source="ops_note"))
    assert hits and hits[0].external_id == "test-syn-001"
    assert all(h.in_lexical and not h.in_dense for h in hits)


@pytest.mark.db
def test_dense_mode_uses_only_the_vector_channel(indexed):
    r = Retriever(HashEmbedder())
    hits = mine(r.search(indexed, "bird strike on departure", mode="dense", rerank=False,
                         source="ops_note"))
    assert hits and hits[0].external_id == "test-syn-004"
    assert all(h.in_dense and not h.in_lexical for h in hits)


@pytest.mark.db
def test_hybrid_fuses_both_channels(indexed):
    r = Retriever(HashEmbedder())
    hits = mine(r.search(indexed, "taxiway closed between A and F reroute", rerank=False,
                         source="ops_note"))
    assert hits[0].external_id == "test-syn-002"
    assert hits[0].in_dense and hits[0].in_lexical
    # RRF: a chunk in both channels outscores one in a single channel at the same rank.
    both = [h for h in hits if h.in_dense and h.in_lexical]
    single = [h for h in hits if h.in_dense != h.in_lexical]
    if both and single:
        assert max(h.fused_score for h in both) > min(h.fused_score for h in single)


@pytest.mark.db
def test_icao_filter_keeps_airport_and_general_docs(indexed):
    r = Retriever(HashEmbedder())
    hits = mine(r.search(indexed, "closed maintenance arrival departure", icao="KZZX",
                         rerank=False, source="ops_note", k=10))
    assert hits and {h.icao for h in hits} <= {"KZZX", None}
    assert not any(h.external_id == "test-syn-001" for h in hits)     # KZZY excluded


@pytest.mark.db
def test_reranker_reorders_and_scores(indexed):
    r = Retriever(HashEmbedder(), SubstringReranker("Bird strike"))
    hits = mine(r.search(indexed, "closed runway taxiway lighting", k=10, source="ops_note"))
    assert hits[0].external_id == "test-syn-004" and hits[0].rerank_score == 1.0
    assert all(h.rerank_score is not None for h in hits)


@pytest.mark.db
def test_k_limits_results_and_ref_is_stable(indexed):
    hits = Retriever(HashEmbedder()).search(indexed, "closed", k=2, rerank=False, source="ops_note")
    assert len(hits) == 2 and hits[0].ref.startswith("ops_note:") and "#0" in hits[0].ref


@pytest.mark.db
def test_empty_corpus_source_returns_nothing(db):
    hits = Retriever(HashEmbedder()).search(db, "anything", source="far_aim", rerank=False)
    assert hits == []


# ---------------------------------------------------------------- real models (opt-in)

@pytest.mark.ml
@pytest.mark.db
def test_real_models_rank_the_taxiway_narrative_first(indexed):
    from preflight.retrieval.embed import STEmbedder, STReranker

    emb = STEmbedder()
    for ext, (icao, text) in SYNTHETIC_NOTES.items():          # re-embed with the real model
        index_document(indexed, emb, source="ops_note", external_id=f"test-{ext}", text=text,
                       icao=icao)
    hits = mine(Retriever(emb, STReranker()).search(
        indexed, "aircraft lined up with a taxiway at night with the parallel runway closed",
        k=10, source="ops_note",
    ))
    assert hits[0].external_id == "test-syn-001"
    assert hits[0].rerank_score is not None and hits[0].rerank_score > hits[1].rerank_score
