"""Fine-tune the cross-encoder reranker on the same synopsis → narrative pairs as the embedder.

After the embedder was fine-tuned, the stock ``bge-reranker-base`` started to reorder its results
worse (rerank lift +0.056 → −0.092, evals/retrieval/HISTORY.md run 10). The reranker was never
shown this register. This trains it on the pairs ``finetune.build_pairs`` produces, so the same
leakage guarantee holds: no report an eval reads is in them.

A cross-encoder learns from negatives as well as positives. Each synopsis gets its own narrative
(label 1) and ``num_negatives`` narratives of *other* reports (label 0), mined with the
fine-tuned embedder so they are plausible rather than random. The nearest neighbours are
skipped on purpose: a short synopsis ("C172 instructor reported an engine failure") matches
hundreds of reports equally well (run 9), so the top of the list is mostly unlabelled positives,
and training on them as negatives would teach the model to reject correct answers. Negatives are
drawn from ranks ``rank_min``..``rank_max`` and must score below the true pair.

``train_reranker`` needs the ``ml`` extra and, realistically, a CUDA GPU
(``notebooks/finetune_reranker_colab.ipynb``).
"""

from __future__ import annotations

import json
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from preflight.retrieval.embed import query_prefix
from preflight.retrieval.finetune import Pair


def select_negatives(
    ranked: Sequence[int], scores: Sequence[float], *, own: int, reports: Sequence[str],
    pos_score: float, k: int, rank_min: int, rank_max: int, rng: random.Random,
) -> list[int]:
    """Up to ``k`` hard-negative indices for pair ``own``.

    ``ranked`` are pair indices by descending similarity to ``own``'s query, ``scores`` their
    similarities. Rank is counted after dropping every pair from ``own``'s report, and a
    candidate scoring at or above the true pair is skipped as a likely unlabelled positive.
    """
    window: list[int] = []
    rank = 0
    for j, s in zip(ranked, scores, strict=True):
        if reports[j] == reports[own]:
            continue
        if rank_min <= rank < rank_max and s < pos_score:
            window.append(j)
        rank += 1
        if rank >= rank_max:
            break
    return sorted(rng.sample(window, min(k, len(window))))


def mine_negatives(
    pairs: Sequence[Pair], *, embedder: str, num_negatives: int = 5, rank_min: int = 10,
    rank_max: int = 50, seed: int = 13, batch_size: int = 256, device: str | None = None,
) -> list[list[int]]:
    """For every pair, indices of other pairs whose narratives are its hard negatives."""
    import torch
    from sentence_transformers import SentenceTransformer

    from preflight.retrieval.embed import _device

    model = SentenceTransformer(embedder, device=device or _device())
    prefix = query_prefix(embedder)
    q = model.encode([prefix + p.query for p in pairs], batch_size=batch_size,
                     normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=True)
    d = model.encode([p.positive for p in pairs], batch_size=batch_size,
                     normalize_embeddings=True, convert_to_tensor=True, show_progress_bar=True)
    pos = (q * d).sum(dim=-1).tolist()
    reports = [p.report for p in pairs]
    rng = random.Random(seed)
    out: list[list[int]] = []
    depth = min(len(pairs), rank_max + 16)      # slack for same-report pairs dropped
    for start in range(0, len(pairs), 1024):
        sims = q[start:start + 1024] @ d.T
        top = torch.topk(sims, k=depth, dim=1)
        for row, (idx, val) in enumerate(zip(top.indices.tolist(), top.values.tolist(),
                                             strict=True)):
            i = start + row
            out.append(select_negatives(idx, val, own=i, reports=reports, pos_score=pos[i],
                                        k=num_negatives, rank_min=rank_min, rank_max=rank_max,
                                        rng=rng))
    return out


def train_reranker(
    pairs: Sequence[Pair], *, embedder: str, out: Path, base: str = "BAAI/bge-reranker-base",
    num_negatives: int = 5, rank_min: int = 10, rank_max: int = 50, epochs: int = 1,
    batch_size: int = 32, lr: float = 2e-5, max_length: int = 384, device: str | None = None,
    resume: bool = False, save_steps: int = 250,
) -> dict[str, Any]:
    """Binary cross-entropy on (synopsis, narrative, 0/1) rows; positives weighted by the
    negative count so each synopsis's one positive balances its negatives. Mined negatives are
    cached in ``out/negatives.json`` so a resumed run does not mine again."""
    import torch
    from datasets import Dataset
    from sentence_transformers.cross_encoder import (
        CrossEncoder,
        CrossEncoderTrainer,
        CrossEncoderTrainingArguments,
    )
    from sentence_transformers.cross_encoder.losses import BinaryCrossEntropyLoss

    from preflight.retrieval.embed import _device

    dev = device or _device()
    out.mkdir(parents=True, exist_ok=True)
    cache = out / "negatives.json"
    if cache.exists():
        negs: list[list[int]] = json.loads(cache.read_text())
        assert len(negs) == len(pairs), f"{cache} was mined for a different pairs file"
    else:
        negs = mine_negatives(pairs, embedder=embedder, num_negatives=num_negatives,
                              rank_min=rank_min, rank_max=rank_max, device=dev)
        cache.write_text(json.dumps(negs))
    rows: dict[str, list[Any]] = {"query": [], "passage": [], "label": []}
    for p, ns in zip(pairs, negs, strict=True):
        for text, label in ((p.positive, 1.0), *((pairs[j].positive, 0.0) for j in ns)):
            rows["query"].append(p.query)
            rows["passage"].append(text)
            rows["label"].append(label)
    ds = Dataset.from_dict(rows)

    model = CrossEncoder(base, num_labels=1, max_length=max_length, device=dev)
    loss = BinaryCrossEntropyLoss(model, pos_weight=torch.tensor(float(num_negatives)))
    args = CrossEncoderTrainingArguments(
        output_dir=str(out / "checkpoints"), num_train_epochs=epochs,
        per_device_train_batch_size=batch_size, learning_rate=lr, warmup_ratio=0.1,
        logging_steps=100, report_to="none", seed=13,
        save_strategy="steps", save_steps=save_steps, save_total_limit=2,
        fp16=dev.startswith("cuda"),
    )
    ckpt = out / "checkpoints"
    has_ckpt = ckpt.is_dir() and any(ckpt.glob("checkpoint-*"))
    CrossEncoderTrainer(model=model, args=args, train_dataset=ds, loss=loss).train(
        resume_from_checkpoint=resume and has_ckpt,
    )
    # Briefings keep a precedent only above a reranker *probability* (precedent_min_score 0.5),
    # as the stock model outputs; a freshly trained head would save raw logits.
    model.activation_fn = torch.nn.Sigmoid()
    model.save_pretrained(str(out))
    n_neg = sum(len(n) for n in negs)
    card = {"base": base, "mined_with": embedder, "pairs": len(pairs), "negatives": n_neg,
            "rank_window": [rank_min, rank_max], "epochs": epochs, "batch_size": batch_size,
            "lr": lr, "max_length": max_length,
            "held_out": "retrieval golden targets + precedent hits (see finetune.held_out_ids)"}
    (out / "preflight_rerank_finetune.json").write_text(json.dumps(card, indent=2) + "\n")
    return card
