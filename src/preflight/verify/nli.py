"""Natural-language-inference scorer behind a one-method protocol.

Default model: ``MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli`` — on the
briefing's own claim phrasings it separated true from corrupted claims with
entailment ≥ 0.96 vs ≤ 0.02 once the premise was contraction-expanded (an
MNLI model does not know that ``CLSD`` means closed; the dictionary from the
decoder does). ``…-large-…-ling-wanli`` is crisper and 2× the load time; it is
the documented upgrade, not the default.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from preflight.config import settings


@runtime_checkable
class Verifier(Protocol):
    name: str

    def entailment(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        """P(entailment) for each (premise, hypothesis)."""
        ...


class HFVerifier:
    def __init__(self, model: str | None = None):
        self.name = model or settings().nli_model
        self._tok: Any = None
        self._model: Any = None
        self._ent_index = 0
        self._device = "cpu"

    def _load(self) -> None:
        if self._model is not None:
            return
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        configured = settings().device
        self._device = (
            configured if configured != "auto"
            else ("mps" if torch.backends.mps.is_available() else "cpu")
        )
        self._tok = AutoTokenizer.from_pretrained(self.name)
        self._model = AutoModelForSequenceClassification.from_pretrained(self.name)
        self._model.to(self._device).eval()
        labels = {int(k): str(v).lower() for k, v in self._model.config.id2label.items()}
        self._ent_index = next(i for i, v in labels.items() if v.startswith("entail"))

    def entailment(self, pairs: Sequence[tuple[str, str]]) -> list[float]:
        if not pairs:
            return []
        self._load()
        import torch

        out: list[float] = []
        with torch.no_grad():
            for i in range(0, len(pairs), 16):
                batch = pairs[i:i + 16]
                x = self._tok([p for p, _ in batch], [h for _, h in batch], return_tensors="pt",
                              truncation=True, padding=True, max_length=512).to(self._device)
                probs = torch.softmax(self._model(**x).logits, dim=-1)[:, self._ent_index]
                out.extend(float(v) for v in probs.cpu())
        return out
