"""Embedder ablation: is a bigger embedding model the lever for Recall@20?

The retrieval eval put hybrid+rerank Recall@20 at 0.61 against a 0.90 target,
and its history argues the ceiling is the embedder, not the candidate pool
(``evals/retrieval/HISTORY.md``, run 5). Re-embedding the 316k-chunk corpus
with a larger model costs hours of GPU per candidate, so this is the cheap
question first: on a fixed subset of the corpus, does model B rank the target
narrative higher than model A for the same 300 synopsis queries?

The subset is every narrative chunk of the 300 target reports plus a random
sample of other narrative chunks, embedded once per model into memory, and
scored by exact cosine search — no database, no index, no reranker. Absolute
numbers are therefore *higher* than the retrieval eval's (fewer distractors,
exact search) and are not comparable to it; only the gap between models
means anything. A model that wins here earns the full re-embed and the real
eval; a model that does not is a few hours saved.

What the first use taught (run 7 in ``evals/retrieval/HISTORY.md``): the subset
prices ranking quality — nDCG and Recall@5 transferred — but overstates recall
at depth, because 16× fewer distractors means the target competes with hundreds
of near neighbours rather than thousands. Recall@20 here is an upper bound.
"""

from __future__ import annotations

import json
import random
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from psycopg import Connection

from preflight.evals.retrieval import SYNOPSIS_MARK, Query, load_golden, ndcg_at, recall_at

RESULTS = Path("evals/embedder/RESULTS.md")
RUNS = Path("evals/embedder/runs")

DEFAULT_MODELS = ("BAAI/bge-base-en-v1.5", "BAAI/bge-large-en-v1.5", "BAAI/bge-m3")


@dataclass(frozen=True)
class Passage:
    external_id: str
    text: str


def build_subset(conn: Connection[Any], queries: list[Query], *, size: int,
                 seed: int = 7) -> list[Passage]:
    """Every narrative chunk of the target reports, plus random narrative chunks up to ``size``."""
    targets = sorted({r for q in queries for r in q.relevant})
    rows = conn.execute(
        "SELECT d.external_id, c.text FROM chunks c JOIN documents d ON d.id = c.document_id "
        "WHERE d.external_id = ANY(%s) AND c.text NOT LIKE %s ORDER BY d.external_id, c.ordinal",
        (targets, SYNOPSIS_MARK),
    ).fetchall()
    must = [Passage(e, t) for e, t in rows]
    n_more = max(size - len(must), 0)
    # TABLESAMPLE is cheap and good enough for distractors; oversample, then trim.
    extra = conn.execute(
        "SELECT d.external_id, c.text FROM chunks c TABLESAMPLE SYSTEM (%s) "
        "JOIN documents d ON d.id = c.document_id "
        "WHERE c.text NOT LIKE %s AND NOT (d.external_id = ANY(%s)) LIMIT %s",
        (min(100.0, 100.0 * n_more * 1.5 / 316_000 + 0.5), SYNOPSIS_MARK, targets, n_more * 2),
    ).fetchall()
    rng = random.Random(seed)
    rng.shuffle(extra)
    return must + [Passage(e, t) for e, t in extra[:n_more]]


def score_model(model: str, queries: list[Query], passages: list[Passage], *,
                batch_size: int = 32) -> dict[str, Any]:
    """Embed everything with one model and rank by exact cosine similarity."""
    import numpy as np

    from preflight.retrieval.embed import STEmbedder

    emb = STEmbedder(model, batch_size=batch_size)
    t0 = perf_counter()
    p_vecs = np.asarray(emb.encode([p.text for p in passages]), dtype=np.float32)
    embed_s = perf_counter() - t0
    q_vecs = np.asarray(emb.encode([q.text for q in queries], query=True), dtype=np.float32)
    sims = q_vecs @ p_vecs.T                                  # normalised → cosine
    ext = [p.external_id for p in passages]
    r5 = r10 = r20 = nd10 = 0.0
    for qi, q in enumerate(queries):
        order = np.argsort(-sims[qi])[:200]
        ranked: list[str] = []
        for j in order:
            if ext[j] not in ranked:
                ranked.append(ext[j])
            if len(ranked) == 20:
                break
        r5 += recall_at(ranked, q.relevant, 5)
        r10 += recall_at(ranked, q.relevant, 10)
        r20 += recall_at(ranked, q.relevant, 20)
        nd10 += ndcg_at(ranked, q.relevant, 10)
    n = len(queries)
    return {
        "model": model, "dim": int(p_vecs.shape[1]),
        "recall_at_5": round(r5 / n, 4), "recall_at_10": round(r10 / n, 4),
        "recall_at_20": round(r20 / n, 4), "ndcg_at_10": round(nd10 / n, 4),
        "embed_seconds": round(embed_s, 1),
        "chunks_per_second": round(len(passages) / embed_s, 1) if embed_s else None,
    }


def run(conn: Connection[Any], *, models: tuple[str, ...] = DEFAULT_MODELS,
        size: int = 40_000, limit: int | None = None) -> dict[str, Any]:
    queries = [q for q in load_golden() if q.kind == "synopsis"]
    if limit:
        queries = queries[:limit]
    passages = build_subset(conn, queries, size=size)
    results = [score_model(m, queries, passages) for m in models]
    return {
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"), "git_sha": _git_sha(),
        "queries": len(queries), "passages": len(passages),
        "target_reports": len({r for q in queries for r in q.relevant}),
        "models": results,
    }


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def to_markdown(res: dict[str, Any]) -> str:
    base = res["models"][0]
    lines = [
        "# Embedder ablation", "",
        f"Run `{res['git_sha']}` at {res['ran_at']} · {res['queries']} synopsis queries · "
        f"{res['passages']:,} narrative chunks ({res['target_reports']} target reports, the rest "
        "random) · exact cosine search in memory, no reranker", "",
        "| model | dim | Recall@5 | Recall@10 | Recall@20 | nDCG@10 | Δ R@20 vs first | "
        "chunks/s |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for m in res["models"]:
        delta = m["recall_at_20"] - base["recall_at_20"]
        lines.append(
            f"| `{m['model']}` | {m['dim']} | {m['recall_at_5']:.3f} | {m['recall_at_10']:.3f} | "
            f"{m['recall_at_20']:.3f} | {m['ndcg_at_10']:.3f} | {delta:+.3f} | "
            f"{m['chunks_per_second'] or '—'} |"
        )
    lines += [
        "",
        "Numbers here are higher than `evals/retrieval/RESULTS.md` by construction — a "
        f"{res['passages']:,}-chunk subset and exact search instead of 316k chunks through "
        "HNSW — and are not comparable to it. Only the gap between rows is the finding. "
        "A model that wins here earns a full re-embed and the real eval.",
        "",
        "**What transferred (run 7, `evals/retrieval/HISTORY.md`):** the ranking gains did — "
        "full-corpus dense nDCG@10 +0.04, Recall@5 +0.08 — and the Recall@20 gain did not "
        "(+0.01 dense, flat after reranking). With 16× fewer distractors than the corpus, a "
        "subset measures how well a model orders near neighbours, not how often the target is "
        "anywhere in the top 20 of 316k chunks. Read the Recall@20 column here as an upper "
        "bound, and the nDCG column as the number to believe.",
    ]
    return "\n".join(lines) + "\n"


def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = res["ran_at"].replace(":", "").replace("-", "")[:15]
    p = RUNS / f"{stamp}-{res['git_sha']}.json"
    p.write_text(json.dumps(res, indent=2) + "\n")
    RESULTS.write_text(to_markdown(res))
    return p, RESULTS
