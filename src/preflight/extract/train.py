"""Fine-tune a token classifier on the synthetic NOTAMs; evaluate on gold and synthetic.

A plain PyTorch loop rather than ``Trainer``: it is forty lines, runs on MPS
without surprises, and there is nothing here that needs callbacks. Word-level
BIO tags are aligned to sub-word tokens the standard way — the first sub-token
of a word carries the label, the rest are ignored (-100) — and inference reads
the first sub-token back (``model.load_predictor``).

The saved directory is a normal ``transformers`` model plus ``preflight.json``
recording what it was trained on, so the model card cannot quietly forget that
the training data was generated.
"""

from __future__ import annotations

import json
import random
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from preflight.extract.labels import TAG_ID, TAGS

DEFAULT_MODEL = "answerdotai/ModernBERT-base"
MODELS_DIR = Path("models")


def _rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def encode(tok: Any, rows: list[dict[str, Any]], max_length: int = 192) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        enc = tok(r["tokens"], is_split_into_words=True, truncation=True, max_length=max_length)
        labels, seen = [], set()
        for wid in enc.word_ids():
            if wid is None or wid in seen:
                labels.append(-100)
            else:
                seen.add(wid)
                labels.append(TAG_ID[r["tags"][wid]])
        out.append({"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"],
                    "labels": labels})
    return out


def _batches(rows: list[dict[str, Any]], size: int, pad_id: int, rng: random.Random | None
             ) -> Iterator[dict[str, Any]]:
    import torch

    order = list(range(len(rows)))
    if rng:
        rng.shuffle(order)
    def pad(chunk: list[dict[str, Any]], key: str, value: int) -> Any:
        width = max(len(c["input_ids"]) for c in chunk)
        return torch.tensor([c[key] + [value] * (width - len(c[key])) for c in chunk])

    for i in range(0, len(order), size):
        chunk = [rows[j] for j in order[i:i + size]]
        yield {"input_ids": pad(chunk, "input_ids", pad_id),
               "attention_mask": pad(chunk, "attention_mask", 0),
               "labels": pad(chunk, "labels", -100)}


def train(
    *, base_model: str = DEFAULT_MODEL, data_dir: Path = Path("data/extract"),
    out_dir: Path | None = None, epochs: int = 3, batch_size: int = 16, lr: float = 5e-5,
    seed: int = 7, log: Callable[[str], None] | None = print, limit: int | None = None,
) -> Path:
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    torch.manual_seed(seed)
    rng = random.Random(seed)
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    out_dir = out_dir or MODELS_DIR / "notam-extractor"
    tok = AutoTokenizer.from_pretrained(base_model)
    model = AutoModelForTokenClassification.from_pretrained(
        base_model, num_labels=len(TAGS), id2label=dict(enumerate(TAGS)),
        label2id=TAG_ID).to(device)
    train_rows = _rows(data_dir / "train.jsonl")[:limit]
    val_rows = _rows(data_dir / "val.jsonl")[: (limit // 10 if limit else None)]
    train_enc, val_enc = encode(tok, train_rows), encode(tok, val_rows)
    pad_id = tok.pad_token_id if tok.pad_token_id is not None else 0

    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.01)
    steps = epochs * ((len(train_enc) + batch_size - 1) // batch_size)
    sched = torch.optim.lr_scheduler.LambdaLR(
        opt, lambda s: min(1.0, s / max(1, steps // 20)) * max(0.0, 1 - s / steps))
    t0, step = time.perf_counter(), 0
    for epoch in range(epochs):
        model.train()
        total = 0.0
        for batch in _batches(train_enc, batch_size, pad_id, rng):
            batch = {k: v.to(device) for k, v in batch.items()}
            loss = model(**batch).loss
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            sched.step()
            opt.zero_grad()
            total += loss.item()
            step += 1
            if log and step % 50 == 0:
                log(f"epoch {epoch + 1} step {step}/{steps} loss {loss.item():.4f} "
                    f"{time.perf_counter() - t0:.0f}s")
        acc = _token_accuracy(model, val_enc, batch_size, pad_id, device)
        if log:
            log(f"epoch {epoch + 1}: mean loss {total / max(1, step):.4f} · "
                f"val token accuracy {acc:.4f}")

    out_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(out_dir)
    tok.save_pretrained(out_dir)
    (out_dir / "preflight.json").write_text(json.dumps({
        "base_model": base_model, "training_data": "synthetic (preflight.extract.synth)",
        "train_examples": len(train_enc), "val_examples": len(val_enc), "epochs": epochs,
        "batch_size": batch_size, "lr": lr, "seed": seed, "tags": list(TAGS),
        "trained_seconds": round(time.perf_counter() - t0), "device": device,
    }, indent=2) + "\n")
    return out_dir


def _token_accuracy(model: Any, rows: list[dict[str, Any]], batch_size: int, pad_id: int,
                    device: str) -> float:
    import torch

    model.eval()
    correct = total = 0
    with torch.no_grad():
        for batch in _batches(rows, batch_size, pad_id, None):
            batch = {k: v.to(device) for k, v in batch.items()}
            pred = model(**batch).logits.argmax(-1)
            mask = batch["labels"] != -100
            correct += int((pred[mask] == batch["labels"][mask]).sum())
            total += int(mask.sum())
    return correct / total if total else 0.0
