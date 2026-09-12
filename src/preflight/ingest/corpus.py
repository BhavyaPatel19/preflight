"""Precedent-corpus ingestion: ASRS and NTSB."""

from __future__ import annotations

from collections.abc import Iterator
from time import perf_counter
from typing import Any

import structlog

from preflight.db import get_pool
from preflight.retrieval.embed import Embedder
from preflight.retrieval.search import DocInput, index_documents
from preflight.sources import asrs, ntsb

log = structlog.get_logger(__name__)


def _already_indexed(conn: Any, source: str, model: str) -> set[str]:
    rows = conn.execute(
        """
        SELECT d.external_id FROM documents d
        WHERE d.source = %s AND EXISTS (
            SELECT 1 FROM chunks c WHERE c.document_id = d.id AND c.embedding_model = %s
        )
        """,
        (source, model),
    ).fetchall()
    return {r[0] for r in rows}


def _asrs_docs(reports: Iterator[asrs.AsrsReport], skip: set[str]) -> Iterator[DocInput]:
    for r in reports:
        if r.acn in skip:
            continue
        yield DocInput(
            source="asrs", external_id=r.acn, text=r.text,
            title=(r.synopsis or "")[:200] or None, published=r.published, icao=r.icao,
            metadata=r.metadata, phases=tuple(p.value for p in r.phases),
        )


def ingest_asrs(
    embedder: Embedder,
    *,
    splits: tuple[str, ...] = asrs.SPLITS,
    limit: int | None = None,
    commit_every: int = 512,
) -> dict[str, Any]:
    """Download (if needed), parse, chunk, embed and store ASRS reports.

    Resumable: reports already embedded with this model are skipped, and work is
    committed every ``commit_every`` documents so an interrupted run keeps its
    progress.
    """
    t0 = perf_counter()
    total_docs = total_chunks = 0
    with get_pool().connection() as conn:
        skip = _already_indexed(conn, "asrs", embedder.name)
        log.info("asrs.start", splits=splits, already_indexed=len(skip), limit=limit)

        def reports() -> Iterator[asrs.AsrsReport]:
            n = 0
            for split in splits:
                for rep in asrs.iter_reports(asrs.download(split)):
                    if limit is not None and n >= limit:
                        return
                    n += 1
                    yield rep

        pending: list[DocInput] = []
        for doc in _asrs_docs(reports(), skip):
            pending.append(doc)
            if len(pending) >= commit_every:
                d, c = index_documents(conn, embedder, pending)
                conn.commit()
                total_docs += d
                total_chunks += c
                pending.clear()
                log.info("asrs.progress", docs=total_docs, chunks=total_chunks,
                         rate_docs_per_s=round(total_docs / (perf_counter() - t0), 1))
        if pending:
            d, c = index_documents(conn, embedder, pending)
            conn.commit()
            total_docs += d
            total_chunks += c

    elapsed = perf_counter() - t0
    log.info("asrs.done", docs=total_docs, chunks=total_chunks, seconds=round(elapsed, 1))
    return {"docs": total_docs, "chunks": total_chunks, "skipped": len(skip),
            "seconds": round(elapsed, 1)}


def _ntsb_docs(events: Iterator[ntsb.NtsbEvent], skip: set[str]) -> Iterator[DocInput]:
    for e in events:
        if e.ev_id in skip:
            continue
        yield DocInput(
            source="ntsb", external_id=e.ev_id, text=e.text, title=e.title,
            published=e.date, icao=e.icao, metadata=e.metadata,
            phases=tuple(p.value for p in e.phases),
        )


def ingest_ntsb(
    embedder: Embedder, *, limit: int | None = None, commit_every: int = 256
) -> dict[str, Any]:
    """Export the NTSB tables (first run), assemble events, chunk, embed, store. Resumable."""
    t0 = perf_counter()
    total_docs = total_chunks = 0
    with get_pool().connection() as conn:
        skip = _already_indexed(conn, "ntsb", embedder.name)
        log.info("ntsb.start", already_indexed=len(skip), limit=limit)

        def events() -> Iterator[ntsb.NtsbEvent]:
            for n, e in enumerate(ntsb.iter_events()):
                if limit is not None and n >= limit:
                    return
                yield e

        pending: list[DocInput] = []
        for doc in _ntsb_docs(events(), skip):
            pending.append(doc)
            if len(pending) >= commit_every:
                d, c = index_documents(conn, embedder, pending)
                conn.commit()
                total_docs += d
                total_chunks += c
                pending.clear()
                log.info("ntsb.progress", docs=total_docs, chunks=total_chunks,
                         rate_docs_per_s=round(total_docs / (perf_counter() - t0), 1))
        if pending:
            d, c = index_documents(conn, embedder, pending)
            conn.commit()
            total_docs += d
            total_chunks += c

    elapsed = perf_counter() - t0
    log.info("ntsb.done", docs=total_docs, chunks=total_chunks, seconds=round(elapsed, 1))
    return {"docs": total_docs, "chunks": total_chunks, "skipped": len(skip),
            "seconds": round(elapsed, 1)}
