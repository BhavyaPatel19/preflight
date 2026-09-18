"""Inference wrapper for the fine-tuned token classifier (training lives in ``train.py``)."""

from __future__ import annotations

from pathlib import Path

from preflight.extract.labels import Span, spans_from_tags, tokenize


def load_predictor(model_dir: Path):  # type: ignore[no-untyped-def]
    """A ``text -> spans`` callable over a saved ``transformers`` token-classification model."""
    import torch
    from transformers import AutoModelForTokenClassification, AutoTokenizer

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tok = AutoTokenizer.from_pretrained(model_dir)
    model = AutoModelForTokenClassification.from_pretrained(model_dir).to(device).eval()
    id2label = {int(k): v for k, v in model.config.id2label.items()}

    def predict(text: str) -> list[Span]:
        words = [w for w, _, _ in tokenize(text)]
        if not words:
            return []
        enc = tok(words, is_split_into_words=True, return_tensors="pt", truncation=True,
                  max_length=256)
        with torch.no_grad():
            logits = model(**{k: v.to(device) for k, v in enc.items()}).logits[0]
        pred_ids = logits.argmax(-1).tolist()
        word_ids = enc.word_ids()
        tags = ["O"] * len(words)
        seen: set[int] = set()
        for pos, wid in enumerate(word_ids):
            if wid is None or wid in seen:
                continue
            seen.add(wid)
            tags[wid] = id2label[pred_ids[pos]]
        return spans_from_tags(text, tags)

    return predict
