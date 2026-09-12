from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Literal

from psycopg import Connection

from preflight.config import settings
from preflight.db import corpus
from preflight.retrieval.chunk import chunk_text
from preflight.retrieval.embed import Embedder, Reranker

Mode = Literal["hybrid", "dense", "lexical"]


@dataclass(frozen=True)
class Hit:
    chunk_id: int
    document_id: int
    source: str
    external_id: str
    title: str | None
    ordinal: int
    text: str
    icao: str | None
    fused_score: float
    in_dense: bool
    in_lexical: bool
    rerank_score: float | None = None

    @property
    def ref(self) -> str:
        return f"{self.source}:{self.external_id}#{self.ordinal}"


class Retriever:
    def __init__(self, embedder: Embedder, reranker: Reranker | None = None):
        self.embedder = embedder
        self.reranker = reranker

    def search(
        self,
        conn: Connection[Any],
        query: str,
        *,
        k: int = 10,
        icao: str | None = None,
        source: str | None = None,
        mode: Mode = "hybrid",
        rerank: bool = True,
        candidates: int | None = None,
    ) -> list[Hit]:
        """Fused candidates from Postgres, optionally reranked; top ``k``."""
        n = candidates or settings().retrieval_candidates
        qvec = self.embedder.encode([query], query=True)[0] if mode != "lexical" else None
        found = corpus.hybrid_search(
            conn,
            query_text=query, query_vec=qvec,
            limit=n, candidates=n, rrf_k=settings().rrf_k,
            w_dense=0.0 if mode == "lexical" else 1.0,
            w_lex=0.0 if mode == "dense" else 1.0,
            icao=icao, source=source,
        )
        hits = [Hit(*c) for c in found]
        if rerank and self.reranker is not None and hits:
            scores = self.reranker.score(query, [h.text for h in hits])
            hits = [replace(h, rerank_score=s) for h, s in zip(hits, scores, strict=True)]
            hits.sort(key=lambda h: h.rerank_score or 0.0, reverse=True)
        return hits[:k]


def index_document(
    conn: Connection[Any],
    embedder: Embedder,
    *,
    source: str,
    external_id: str,
    text: str,
    title: str | None = None,
    published: date | None = None,
    icao: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Upsert a document, chunk it, embed the chunks, store everything. Returns chunk count."""
    doc_id = corpus.upsert_document(
        conn, source=source, external_id=external_id, title=title,
        published=published, icao=icao, metadata=metadata,
    )
    chunks = chunk_text(text)
    vecs = embedder.encode([c.text for c in chunks]) if chunks else []
    return corpus.replace_chunks(
        conn, doc_id, [(c.ordinal, c.text) for c in chunks], vecs,
        embedding_model=embedder.name, icao=icao,
    )
