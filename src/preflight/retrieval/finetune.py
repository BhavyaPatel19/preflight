"""Fine-tune the embedder on the corpus's own paraphrase pairs.

Every ASRS report carries two descriptions of the same event: the reporter's narrative and a
NASA analyst's synopsis of it. That is tens of thousands of natural (query, passage) pairs in the
exact register the retrieval eval asks about — and the embedder ablation located the Recall@20
ceiling in the embedder, not the candidate pool (evals/retrieval/HISTORY.md, run 7).

Leakage is the whole risk. The retrieval eval's 300 queries *are* synopses of 300 reports, and the
precedent eval judges specific reports. Training on any of them would teach the model the answer
key, so :func:`held_out_ids` collects every report id the evals use and :func:`build_pairs`
never reads those reports. The proof is the ablation re-run (``preflight eval embedder``) on the
untouched 300 queries; only a model that wins there earns the full re-embed.

``train`` needs the ``ml`` extra (torch, sentence-transformers, datasets); building pairs does not.
"""

from __future__ import annotations

import json
import random
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from psycopg import Connection

from preflight.evals.retrieval import GOLDEN as RETRIEVAL_GOLDEN
from preflight.retrieval.embed import query_prefix

PRECEDENT_PAIRS = Path("evals/precedent/pairs.jsonl")
_SYNOPSIS = re.compile(r"(?:^|\n)Synopsis:\s*(?P<s>.+)$", re.S)


@dataclass(frozen=True)
class Pair:
    report: str        # ASRS external id
    query: str         # the analyst's synopsis
    positive: str      # a narrative chunk of the same report


def held_out_ids(
    retrieval_golden: Path = RETRIEVAL_GOLDEN, precedent_pairs: Path = PRECEDENT_PAIRS,
) -> set[str]:
    """Every report id an eval reads: the retrieval targets and the judged precedent hits."""
    ids: set[str] = set()
    if retrieval_golden.exists():
        for line in retrieval_golden.read_text().splitlines():
            if line.strip():
                ids.update(json.loads(line).get("relevant") or [])
    if precedent_pairs.exists():
        for line in precedent_pairs.read_text().splitlines():
            if line.strip():
                ref = str(json.loads(line).get("hit_ref") or "")
                if ref.startswith("asrs:"):
                    ids.add(ref.split(":", 1)[1])
    return ids


def pair_from_chunks(report: str, chunks: Sequence[str]) -> Pair | None:
    """(synopsis, first narrative chunk) for one report's chunks in order, if it has both."""
    synopsis = next((m["s"].strip() for c in chunks if (m := _SYNOPSIS.search(c))), None)
    narrative = next((c for c in chunks if "Synopsis:" not in c and c.strip()), None)
    if not synopsis or not narrative or len(synopsis) < 40:
        return None
    return Pair(report=report, query=synopsis, positive=narrative)


def _batched(xs: Sequence[str], n: int) -> Iterable[Sequence[str]]:
    for i in range(0, len(xs), n):
        yield xs[i:i + n]


def build_pairs(
    conn: Connection[Any], *, exclude: set[str], limit: int = 40_000, seed: int = 13,
) -> list[Pair]:
    """Up to ``limit`` training pairs from a seeded sample of ASRS reports outside ``exclude``."""
    ids = [r[0] for r in conn.execute(
        "SELECT external_id FROM documents WHERE source = 'asrs' ORDER BY external_id"
    ).fetchall() if r[0] not in exclude]
    random.Random(seed).shuffle(ids)
    pairs: list[Pair] = []
    # Oversample: some reports have no synopsis or a synopsis-only chunk.
    for batch in _batched(ids[: int(limit * 1.3) + 100], 2_000):
        rows = conn.execute(
            "SELECT d.external_id, c.text FROM chunks c JOIN documents d ON d.id = c.document_id "
            "WHERE d.source = 'asrs' AND d.external_id = ANY(%s) "
            "ORDER BY d.external_id, c.ordinal",
            (list(batch),),
        ).fetchall()
        by_report: dict[str, list[str]] = {}
        for ext, text in rows:
            by_report.setdefault(ext, []).append(text)
        for ext in batch:
            p = pair_from_chunks(ext, by_report.get(ext, []))
            if p is not None:
                pairs.append(p)
                if len(pairs) >= limit:
                    return pairs
    return pairs


def train(
    pairs: Sequence[Pair], *, base: str, out: Path, epochs: int = 1, batch_size: int = 128,
    mini_batch_size: int = 16, lr: float = 2e-5, max_seq_length: int = 256,
    device: str | None = None,
) -> dict[str, Any]:
    """Contrastive fine-tune: each synopsis against its narrative, every other narrative in the
    batch as a negative (MultipleNegativesRankingLoss, cached so a 128-pair batch fits in the
    memory of a 16-pair one). Queries carry the same instruction prefix the retriever adds."""
    from datasets import Dataset
    from sentence_transformers import (
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
        losses,
    )
    from sentence_transformers.training_args import BatchSamplers

    from preflight.retrieval.embed import _device

    model = SentenceTransformer(base, device=device or _device())
    model.max_seq_length = max_seq_length
    prefix = query_prefix(base)
    ds = Dataset.from_dict({
        "anchor": [prefix + p.query for p in pairs],
        "positive": [p.positive for p in pairs],
    })
    loss = losses.CachedMultipleNegativesRankingLoss(model, mini_batch_size=mini_batch_size)
    args = SentenceTransformerTrainingArguments(
        output_dir=str(out / "checkpoints"), num_train_epochs=epochs,
        per_device_train_batch_size=batch_size, learning_rate=lr, warmup_ratio=0.1,
        batch_sampler=BatchSamplers.NO_DUPLICATES, save_strategy="no", logging_steps=25,
        report_to="none", seed=13,
    )
    SentenceTransformerTrainer(model=model, args=args, train_dataset=ds, loss=loss).train()
    out.mkdir(parents=True, exist_ok=True)
    model.save(str(out))
    card = {"base": base, "pairs": len(pairs), "epochs": epochs, "batch_size": batch_size,
            "lr": lr, "max_seq_length": max_seq_length, "query_prefix": prefix,
            "held_out": "retrieval golden targets + precedent hits (see finetune.held_out_ids)"}
    (out / "preflight_finetune.json").write_text(json.dumps(card, indent=2) + "\n")
    return card
