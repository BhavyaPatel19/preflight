"""Hard-negative selection for the reranker fine-tune (pure function, no torch)."""

import random

from preflight.retrieval.rerank_finetune import select_negatives


def _pick(ranked, scores, reports, **kw):
    args = {"own": 0, "pos_score": 0.9, "k": 3, "rank_min": 2, "rank_max": 6,
            "rng": random.Random(0), **kw}
    return select_negatives(ranked, scores, reports=reports, **args)


def test_skips_own_report_and_the_nearest_neighbours() -> None:
    reports = ["r0", "r0", "r2", "r3", "r4", "r5", "r6", "r7", "r8"]
    ranked = [0, 1, 2, 3, 4, 5, 6, 7, 8]
    scores = [0.95, 0.94, 0.8, 0.8, 0.7, 0.7, 0.6, 0.6, 0.5]
    got = _pick(ranked, scores, reports, k=10)
    # pairs 0 and 1 are the query's own report; ranks 0-1 after them (pairs 2, 3) are skipped
    assert got == [4, 5, 6, 7]


def test_drops_candidates_scoring_above_the_true_pair() -> None:
    reports = [f"r{i}" for i in range(8)]
    ranked = [0, 1, 2, 3, 4, 5, 6, 7]
    scores = [1.0, 0.99, 0.98, 0.97, 0.95, 0.5, 0.4, 0.3]
    got = _pick(ranked, scores, reports, k=10)
    assert 3 not in got and 4 not in got      # in the window but above pos_score 0.9
    assert got == [5, 6]                     # pair 7 is rank 6, outside the window


def test_samples_k_and_is_deterministic() -> None:
    reports = [f"r{i}" for i in range(40)]
    ranked = list(range(40))
    scores = [0.5] * 40
    a = _pick(ranked, scores, reports, k=3, rank_min=5, rank_max=30)
    b = _pick(ranked, scores, reports, k=3, rank_min=5, rank_max=30)
    assert a == b and len(a) == 3 and all(6 <= j < 31 for j in a)
