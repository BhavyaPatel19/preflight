"""Retrieval: chunk → embed → hybrid search → rerank.

Hybrid on purpose. Aviation queries are full of exact identifiers — ``28R``,
``KSFO``, ``ILS 22L`` — that embeddings blur and lexical search nails; the
narrative side ("lined up on the taxiway at night") is the reverse. Dense and
lexical candidate sets are fused with reciprocal rank fusion inside Postgres,
then a cross-encoder reranks the top of the fused list. See docs/adr/0003.
"""

from preflight.retrieval.chunk import chunk_text
from preflight.retrieval.embed import Embedder, Reranker
from preflight.retrieval.search import Hit, Retriever

__all__ = ["Embedder", "Hit", "Reranker", "Retriever", "chunk_text"]
