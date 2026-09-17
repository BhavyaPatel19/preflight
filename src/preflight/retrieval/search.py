from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import date
from time import perf_counter
from typing import Any, Literal, NamedTuple

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
        exclude_like: str | None = None,
        icao_strict: bool = False,
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
            icao=icao, source=source, exclude_like=exclude_like, icao_strict=icao_strict,
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


class DocInput(NamedTuple):
    source: str
    external_id: str
    text: str
    title: str | None = None
    published: date | None = None
    icao: str | None = None
    metadata: dict[str, Any] | None = None
    phases: tuple[str, ...] = ()


def index_documents(
    conn: Connection[Any], embedder: Embedder, docs: Iterable[DocInput], *, batch_docs: int = 64
) -> tuple[int, int]:
    """Index many documents, embedding all their chunks per batch in one call.

    Per-document encoding is the slow path (a model call per two chunks); this
    encodes a few hundred chunks at once. Returns (documents, chunks).
    """
    n_docs = n_chunks = 0
    batch: list[DocInput] = []

    def flush() -> None:
        nonlocal n_docs, n_chunks
        if not batch:
            return
        per_doc = [chunk_text(d.text) for d in batch]
        flat = [c.text for cs in per_doc for c in cs]
        vecs = embedder.encode(flat) if flat else []
        i = 0
        for d, cs in zip(batch, per_doc, strict=True):
            doc_id = corpus.upsert_document(
                conn, source=d.source, external_id=d.external_id, title=d.title,
                published=d.published, icao=d.icao, metadata=d.metadata,
            )
            corpus.replace_chunks(
                conn, doc_id, [(c.ordinal, c.text) for c in cs], vecs[i:i + len(cs)],
                embedding_model=embedder.name, icao=d.icao, phases=d.phases,
            )
            i += len(cs)
            n_docs += 1
            n_chunks += len(cs)
        batch.clear()

    for d in docs:
        batch.append(d)
        if len(batch) >= batch_docs:
            flush()
    flush()
    return n_docs, n_chunks


def reembed(
    conn: Connection[Any], embedder: Embedder, *, batch: int = 128, source: str | None = None,
    commit: bool = True, log: Callable[[str], None] | None = None,
) -> int:
    """Re-embed every chunk not already carrying ``embedder.name``.

    Keyset-paginated over ``id`` so each batch is one index range scan however far along
    the run is, and resumable for the same reason: rows already stamped with the model
    are skipped. ``commit`` (per batch) is what makes a five-hour run survivable — pass
    False only inside a transaction you own, such as a test's. ``source`` restricts the
    pass to one document source. Drop the HNSW index first (migration 007 does) and
    rebuild it after with ``reindex``: updating 316k vectors through a live index is the
    slow path.
    """
    t0 = perf_counter()
    done = last_id = 0
    scope = "" if source is None else \
        "AND document_id IN (SELECT id FROM documents WHERE source = %(source)s)"
    params: dict[str, Any] = {"model": embedder.name, "source": source, "batch": batch}
    row = conn.execute(
        f"SELECT count(*) FROM chunks WHERE (embedding IS NULL "
        f"OR embedding_model IS DISTINCT FROM %(model)s) {scope}", params,
    ).fetchone()
    todo = int(row[0]) if row else 0
    while True:
        rows = conn.execute(
            f"SELECT id, text, embedding_model FROM chunks WHERE id > %(last)s {scope} "
            "ORDER BY id LIMIT %(batch)s", {**params, "last": last_id},
        ).fetchall()
        if not rows:
            break
        last_id = rows[-1][0]
        pending = [(i, t) for i, t, m in rows if m != embedder.name]
        if not pending:
            continue
        vecs = embedder.encode([t for _, t in pending])
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE chunks SET embedding = %s, embedding_model = %s WHERE id = %s",
                [(list(v), embedder.name, i) for (i, _), v in zip(pending, vecs, strict=True)],
            )
        if commit:
            conn.commit()
        done += len(pending)
        if log and (done // len(pending)) % 40 == 0:
            rate = done / (perf_counter() - t0)
            eta = (todo - done) / rate / 60 if rate else 0
            log(f"{done:>7,} / {todo:,} chunks  {rate:5.1f}/s  ~{eta:4.0f} min left")
    return done


def reindex_statements(*, m: int = 16, ef_construction: int = 128,
                       maintenance_work_mem: str = "4GB", workers: int = 4) -> list[str]:
    """The SQL to (re)build the corpus HNSW index over the loaded table, in order."""
    return [
        f"SET maintenance_work_mem = '{maintenance_work_mem}'",
        f"SET max_parallel_maintenance_workers = {int(workers)}",
        "DROP INDEX IF EXISTS chunks_embedding_idx",
        "CREATE INDEX chunks_embedding_idx ON chunks USING hnsw (embedding vector_cosine_ops) "
        f"WITH (m = {int(m)}, ef_construction = {int(ef_construction)})",
    ]


def reindex(conn: Connection[Any], *, m: int = 16, ef_construction: int = 128,
            maintenance_work_mem: str = "4GB", workers: int = 4) -> float:
    """Run ``reindex_statements`` and commit. Minutes on the full corpus. Returns seconds."""
    t0 = perf_counter()
    for stmt in reindex_statements(m=m, ef_construction=ef_construction,
                                   maintenance_work_mem=maintenance_work_mem, workers=workers):
        conn.execute(stmt)
    conn.commit()
    return perf_counter() - t0
