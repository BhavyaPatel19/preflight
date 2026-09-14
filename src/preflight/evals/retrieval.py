"""Retrieval evaluation.

Two query sets, both with objective labels and no human or LLM judging:

* **synopsis** — an ASRS report's expert-written synopsis as the query; the
  relevant document is that report. The synopsis is a NASA analyst's paraphrase
  of the narrative, so this is a genuine paraphrase-to-passage task. Because
  synopses were appended into the indexed text, chunks containing one are
  hidden from the search during this eval; the narrative has to be found.
* **identifier** — ``"runway 28R"`` searched *with the airport as a metadata
  filter*, built from (airport, runway) pairs that co-occur in the corpus.
  Relevant = a chunk at that airport mentioning that runway. The airport is a
  filter rather than query text because narratives say "SFO" or "San
  Francisco", never "KSFO" — the ICAO code lives in metadata, and the briefing
  agent filters on it. This is the lexical channel's reason to exist, and where
  dense-only retrieval is expected to fail.

Configs compared: dense, lexical, hybrid, dense+rerank, hybrid+rerank. The
README's "rerank lift" is nDCG@10(hybrid+rerank) − nDCG@10(dense); dense+rerank
shows how much of that the reranker alone accounts for.

What this does NOT measure: whether a briefing-style query ("28R closed,
parallel in use, night") retrieves the *right precedent*. That needs judged
relevance and is the Sprint 5 golden set.
"""

from __future__ import annotations

import json
import math
import random
import re
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

from psycopg import Connection

from preflight.config import settings
from preflight.evals import summary
from preflight.retrieval.embed import Embedder, Reranker
from preflight.retrieval.search import Hit, Retriever

GOLDEN = Path("evals/retrieval/golden.jsonl")
RESULTS = Path("evals/retrieval/RESULTS.md")
RUNS = Path("evals/retrieval/runs")
SYNOPSIS_MARK = "%Synopsis:%"

CONFIGS: tuple[tuple[str, str, bool], ...] = (
    # name, mode, rerank
    ("dense", "dense", False),
    ("lexical", "lexical", False),
    ("hybrid", "hybrid", False),
    ("dense+rerank", "dense", True),
    ("hybrid+rerank", "hybrid", True),
)


@dataclass(frozen=True)
class Query:
    kind: str                       # synopsis | identifier
    id: str
    text: str
    relevant: tuple[str, ...]       # external_ids (synopsis) or [] (identifier: predicate)
    icao: str | None = None
    runway: str | None = None


# --------------------------------------------------------------------------
# Golden set
# --------------------------------------------------------------------------

_RWY = re.compile(r"\b(?:RWY|Runway|runway)\s?(\d{1,2}[LRC]?)\b")


def build_golden(
    conn: Connection[Any], *, n_synopsis: int = 300, n_identifier: int = 50, seed: int = 42
) -> list[Query]:
    rng = random.Random(seed)

    # Synopsis queries: reports with a real synopsis and at least two chunks,
    # so a narrative-only chunk exists once synopsis chunks are hidden.
    rows = conn.execute(
        """
        SELECT d.external_id, d.metadata->>'phases', d.title
        FROM documents d
        WHERE d.source = 'asrs' AND length(coalesce(d.title, '')) >= 60
          AND (SELECT count(*) FROM chunks c WHERE c.document_id = d.id) >= 2
          AND EXISTS (SELECT 1 FROM chunks c WHERE c.document_id = d.id
                      AND c.text NOT LIKE %s)
        ORDER BY d.external_id
        """,
        (SYNOPSIS_MARK,),
    ).fetchall()
    rng.shuffle(rows)
    synopsis = [
        Query(kind="synopsis", id=f"syn-{acn}", text=title.strip(), relevant=(acn,))
        for acn, _phases, title in rows[:n_synopsis]
    ]

    # Identifier queries: (airport, runway) pairs seen together often enough
    # that precision@10 is meaningful.
    pairs: dict[tuple[str, str], int] = {}
    for icao, text in conn.execute(
        "SELECT c.icao, c.text FROM chunks c WHERE c.icao IS NOT NULL AND c.text ~* 'runway|rwy'"
    ):
        for rwy in set(_RWY.findall(text)):
            pairs[(icao, rwy.upper())] = pairs.get((icao, rwy.upper()), 0) + 1
    frequent = sorted((p for p, n in pairs.items() if n >= 5), key=lambda p: (-pairs[p], p))
    rng.shuffle(frequent)
    identifier = [
        Query(kind="identifier", id=f"id-{icao}-{rwy}", text=f"runway {rwy}",
              relevant=(), icao=icao, runway=rwy)
        for icao, rwy in frequent[:n_identifier]
    ]
    return synopsis + identifier


def save_golden(queries: Sequence[Query], path: Path = GOLDEN) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for q in queries:
            f.write(json.dumps(asdict(q)) + "\n")


def load_golden(path: Path = GOLDEN) -> list[Query]:
    out: list[Query] = []
    with path.open() as f:
        for line in f:
            if line.strip():
                d = json.loads(line)
                d["relevant"] = tuple(d["relevant"])
                out.append(Query(**d))
    return out


# --------------------------------------------------------------------------
# Metrics (document level)
# --------------------------------------------------------------------------

def doc_ranking(hits: Sequence[Hit]) -> list[str]:
    """Chunk hits → ordered unique document ids (best chunk wins)."""
    seen: list[str] = []
    for h in hits:
        if h.external_id not in seen:
            seen.append(h.external_id)
    return seen


def recall_at(ranked: Sequence[str], relevant: Sequence[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = set(ranked[:k])
    return sum(1 for r in relevant if r in top) / len(relevant)


def reciprocal_rank(ranked: Sequence[str], relevant: Sequence[str], k: int) -> float:
    rel = set(relevant)
    for i, d in enumerate(ranked[:k], start=1):
        if d in rel:
            return 1.0 / i
    return 0.0


def ndcg_at(ranked: Sequence[str], relevant: Sequence[str], k: int) -> float:
    """Binary relevance. Ideal DCG assumes all relevant docs ranked first."""
    rel = set(relevant)
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(ranked[:k], start=1) if d in rel)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(rel), k) + 1))
    return dcg / ideal if ideal else 0.0


def identifier_hit(h: Hit, icao: str, runway: str) -> bool:
    return h.icao == icao and any(r.upper() == runway for r in _RWY.findall(h.text))


def precision_at(hits: Sequence[Hit], k: int, icao: str, runway: str) -> float:
    top = hits[:k]
    return sum(1 for h in top if identifier_hit(h, icao, runway)) / k if top else 0.0


# --------------------------------------------------------------------------
# Runner
# --------------------------------------------------------------------------

@dataclass
class ConfigResult:
    name: str
    n_synopsis: int = 0
    n_identifier: int = 0
    recall_at_5: float = 0.0
    recall_at_10: float = 0.0
    recall_at_20: float = 0.0
    mrr_at_20: float = 0.0
    ndcg_at_10: float = 0.0
    precision_at_10_identifier: float = 0.0
    latency_ms_p50: float = 0.0
    latency_ms_p95: float = 0.0
    _lat: list[float] = field(default_factory=list, repr=False)


def _git_sha() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True,
                              text=True, check=True).stdout.strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run(
    conn: Connection[Any],
    embedder: Embedder,
    reranker: Reranker | None,
    queries: Sequence[Query],
    *,
    k: int = 20,
    candidates: int = 40,
    configs: Sequence[tuple[str, str, bool]] = CONFIGS,
) -> dict[str, Any]:
    retriever = Retriever(embedder, reranker)
    results: dict[str, ConfigResult] = {name: ConfigResult(name) for name, _, _ in configs}
    sums: dict[str, dict[str, float]] = {name: {} for name, _, _ in configs}

    def add(name: str, key: str, value: float) -> None:
        sums[name][key] = sums[name].get(key, 0.0) + value

    for q in queries:
        for name, mode, rerank in configs:
            if rerank and reranker is None:
                continue
            t0 = perf_counter()
            # Rank the whole candidate pool so document-level @k is not capped by chunk k.
            hits = retriever.search(
                conn, q.text, k=candidates, mode=mode, rerank=rerank, candidates=candidates,  # type: ignore[arg-type]
                source="asrs" if q.kind == "synopsis" else None,
                icao=q.icao if q.kind == "identifier" else None,
                icao_strict=q.kind == "identifier",
                exclude_like=SYNOPSIS_MARK if q.kind == "synopsis" else None,
            )
            results[name]._lat.append((perf_counter() - t0) * 1000)
            if q.kind == "synopsis":
                ranked = doc_ranking(hits)
                results[name].n_synopsis += 1
                add(name, "r5", recall_at(ranked, q.relevant, 5))
                add(name, "r10", recall_at(ranked, q.relevant, 10))
                add(name, "r20", recall_at(ranked, q.relevant, 20))
                add(name, "mrr", reciprocal_rank(ranked, q.relevant, 20))
                add(name, "ndcg", ndcg_at(ranked, q.relevant, 10))
            else:
                assert q.icao and q.runway
                results[name].n_identifier += 1
                add(name, "p10", precision_at(hits, 10, q.icao, q.runway))

    for name, r in results.items():
        s = sums[name]
        if r.n_synopsis:
            r.recall_at_5 = s.get("r5", 0) / r.n_synopsis
            r.recall_at_10 = s.get("r10", 0) / r.n_synopsis
            r.recall_at_20 = s.get("r20", 0) / r.n_synopsis
            r.mrr_at_20 = s.get("mrr", 0) / r.n_synopsis
            r.ndcg_at_10 = s.get("ndcg", 0) / r.n_synopsis
        if r.n_identifier:
            r.precision_at_10_identifier = s.get("p10", 0) / r.n_identifier
        if r._lat:
            lat = sorted(r._lat)
            r.latency_ms_p50 = median(lat)
            r.latency_ms_p95 = lat[min(len(lat) - 1, int(len(lat) * 0.95))]

    corpus = conn.execute(
        "SELECT count(DISTINCT document_id), count(*) FROM chunks WHERE embedding IS NOT NULL"
    ).fetchone()
    assert corpus is not None
    out = {
        "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "git_sha": _git_sha(),
        "embedding_model": embedder.name,
        "reranker_model": reranker.name if reranker else None,
        "corpus_documents": corpus[0], "corpus_chunks": corpus[1],
        "k": k, "candidates": candidates, "rrf_k": settings().rrf_k,
        "queries": {"synopsis": sum(1 for q in queries if q.kind == "synopsis"),
                    "identifier": sum(1 for q in queries if q.kind == "identifier")},
        "configs": {name: {kk: v for kk, v in asdict(r).items() if not kk.startswith("_")}
                    for name, r in results.items() if r.n_synopsis or r.n_identifier},
    }
    if "dense" in out["configs"] and "hybrid+rerank" in out["configs"]:
        out["rerank_lift_ndcg_at_10"] = round(
            out["configs"]["hybrid+rerank"]["ndcg_at_10"] - out["configs"]["dense"]["ndcg_at_10"], 4
        )
    return out


def to_markdown(res: dict[str, Any]) -> str:
    c = res["configs"]
    q = res["queries"]
    head = (
        f"Run `{res['git_sha']}` at {res['ran_at']} · corpus {res['corpus_documents']:,} documents"
        f" / {res['corpus_chunks']:,} chunks · embedder `{res['embedding_model']}` · reranker"
        f" `{res['reranker_model']}` · {res['candidates']} candidates per channel,"
        f" RRF k={res['rrf_k']}"
    )
    lines = [
        "# Retrieval evaluation", "", head, "",
        f"**Synopsis → narrative** ({q['synopsis']} ASRS queries; synopsis chunks hidden):", "",
        "| config | Recall@5 | Recall@10 | Recall@20 | MRR@20 | nDCG@10 | p50 ms | p95 ms |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for name in ("dense", "lexical", "hybrid", "dense+rerank", "hybrid+rerank"):
        if name in c:
            r = c[name]
            lines.append(
                f"| {name} | {r['recall_at_5']:.3f} | {r['recall_at_10']:.3f}"
                f" | {r['recall_at_20']:.3f} | {r['mrr_at_20']:.3f} | {r['ndcg_at_10']:.3f}"
                f" | {r['latency_ms_p50']:.0f} | {r['latency_ms_p95']:.0f} |"
            )
    if "rerank_lift_ndcg_at_10" in res:
        lift = res["rerank_lift_ndcg_at_10"]
        lines += ["", f"**Rerank lift** (nDCG@10, hybrid+rerank − dense): **{lift:+.3f}**"]
    lines += [
        "",
        f"**Identifier queries** ({q['identifier']} `runway <NN>` queries with the airport as a"
        " metadata filter; relevant = chunk at that airport mentioning that runway):",
        "", "| config | P@10 |", "|---|---:|",
    ]
    for name in ("dense", "lexical", "hybrid", "dense+rerank", "hybrid+rerank"):
        if name in c:
            lines.append(f"| {name} | {c[name]['precision_at_10_identifier']:.3f} |")
    lines += [
        "",
        "What this measures: paraphrase-to-passage retrieval and exact-identifier retrieval,",
        "both with objective labels. What it does not: judged precedent relevance for",
        "briefing-style queries — that is the Sprint 5 golden set.",
    ]
    return "\n".join(lines) + "\n"


def summarise(res: dict[str, Any]) -> dict[str, float | None]:
    """Headline numbers for the gate: the deployed config, plus the rerank lift."""
    best = res["configs"].get("hybrid+rerank") or res["configs"].get("hybrid") or {}
    return {
        "hybrid_rerank_ndcg_at_10": best.get("ndcg_at_10"),
        "hybrid_rerank_recall_at_20": best.get("recall_at_20"),
        "hybrid_rerank_precision_at_10_identifier": best.get("precision_at_10_identifier"),
        "hybrid_rerank_latency_ms_p50": best.get("latency_ms_p50"),
        "rerank_lift_ndcg_at_10": res.get("rerank_lift_ndcg_at_10"),
    }

def save_run(res: dict[str, Any]) -> tuple[Path, Path]:
    RUNS.mkdir(parents=True, exist_ok=True)
    stamp = res["ran_at"].replace(":", "").replace("-", "")[:15]
    run_path = RUNS / f"{stamp}-{res['git_sha']}.json"
    run_path.write_text(json.dumps(res, indent=2) + "\n")
    RESULTS.write_text(to_markdown(res))
    summary.write("retrieval", res, summarise(res), embedding_model=res["embedding_model"],
                  reranker_model=res["reranker_model"], corpus_chunks=res["corpus_chunks"])
    return run_path, RESULTS
