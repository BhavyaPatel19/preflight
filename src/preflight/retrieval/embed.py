"""Embedding and reranking behind small protocols.

The sentence-transformers implementations import torch lazily, so the package
stays importable — and the test suite stays fast — on a machine without the ML
extras. Tests use hash-based fakes; ``pytest -m ml`` exercises the real models.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol, runtime_checkable

from preflight.config import settings


@runtime_checkable
class Embedder(Protocol):
    name: str
    dim: int

    def encode(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]: ...


@runtime_checkable
class Reranker(Protocol):
    name: str

    def score(self, query: str, texts: Sequence[str]) -> list[float]: ...


def _device() -> str:
    configured = settings().device
    if configured != "auto":
        return configured
    try:
        import torch

        return "mps" if torch.backends.mps.is_available() else "cpu"
    except ImportError:
        return "cpu"


class STEmbedder:
    """sentence-transformers embedder. bge-style models want a query instruction."""

    _QUERY_PREFIX = {
        "BAAI/bge-base-en-v1.5": "Represent this sentence for searching relevant passages: ",
        "BAAI/bge-small-en-v1.5": "Represent this sentence for searching relevant passages: ",
        "BAAI/bge-large-en-v1.5": "Represent this sentence for searching relevant passages: ",
    }

    def __init__(self, model: str | None = None, *, batch_size: int = 32):
        self.name = model or settings().embedding_model
        self.batch_size = batch_size
        self._model: Any = None
        self.dim = 0

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.name, device=_device())
            getdim = getattr(self._model, "get_embedding_dimension", None) or \
                self._model.get_sentence_embedding_dimension
            self.dim = int(getdim())
        return self._model

    def encode(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        prefix = self._QUERY_PREFIX.get(self.name, "") if query else ""
        vecs = model.encode(
            [prefix + t for t in texts],
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        return [[float(x) for x in v] for v in vecs]


class STReranker:
    def __init__(self, model: str | None = None, *, batch_size: int = 16):
        self.name = model or settings().reranker_model
        self.batch_size = batch_size
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import CrossEncoder

            self._model = CrossEncoder(self.name, device=_device())
        return self._model

    def score(self, query: str, texts: Sequence[str]) -> list[float]:
        if not texts:
            return []
        scores = self._load().predict(
            [(query, t) for t in texts], batch_size=self.batch_size, show_progress_bar=False
        )
        return [float(s) for s in scores]
