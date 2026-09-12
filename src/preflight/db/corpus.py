"""Precedent corpus: documents, chunks, and the hybrid search statement.

One SQL statement does the retrieval: a dense candidate set (HNSW, cosine) and
a lexical candidate set (tsvector, ts_rank_cd), each filtered by the same
metadata, fused with reciprocal rank fusion. Weights of 0 switch a channel off,
which is how the eval ablates dense-only vs lexical-only vs hybrid.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Any, NamedTuple

from psycopg import Connection
from psycopg.types.json import Jsonb

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9/\-]*")


class Candidate(NamedTuple):
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


def upsert_document(
    conn: Connection[Any],
    *,
    source: str,
    external_id: str,
    title: str | None = None,
    published: date | None = None,
    icao: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO documents (source, external_id, title, published, icao, metadata)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (source, external_id) DO UPDATE SET
            title = EXCLUDED.title, published = EXCLUDED.published,
            icao = EXCLUDED.icao, metadata = EXCLUDED.metadata
        RETURNING id
        """,
        (source, external_id, title, published, icao, Jsonb(metadata or {})),
    ).fetchone()
    assert row is not None
    return int(row[0])


def replace_chunks(
    conn: Connection[Any],
    document_id: int,
    chunks: Sequence[tuple[int, str]],
    embeddings: Sequence[Sequence[float]] | None,
    *,
    embedding_model: str | None,
    icao: str | None = None,
    phases: Sequence[str] = (),
) -> int:
    """Replace a document's chunks wholesale — re-chunking is the common case."""
    conn.execute("DELETE FROM chunks WHERE document_id = %s", (document_id,))
    for i, (ordinal, text) in enumerate(chunks):
        vec = list(embeddings[i]) if embeddings is not None else None
        conn.execute(
            """
            INSERT INTO chunks (document_id, ordinal, text, icao, phases, embedding,
                                embedding_model, chars)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (document_id, ordinal, text, icao, list(phases), vec,
             embedding_model if vec is not None else None, len(text)),
        )
    return len(chunks)


def lexical_query(text: str) -> str:
    """OR-join the terms so partial matches still rank; ts_rank_cd rewards more hits."""
    terms = {t.lower() for t in _TOKEN.findall(text) if len(t) > 1}
    return " | ".join(sorted(terms))


_HYBRID = """
WITH params AS (
    SELECT %(qvec)s::vector AS qvec,
           to_tsquery('english', %(qor)s) AS q
),
pool AS (
    SELECT c.id, c.embedding, c.search_tsv
    FROM chunks c JOIN documents d ON d.id = c.document_id
    WHERE (%(icao)s::text IS NULL OR c.icao = %(icao)s OR c.icao IS NULL)
      AND (%(source)s::text IS NULL OR d.source = %(source)s)
),
dense AS (
    SELECT p.id, row_number() OVER (ORDER BY p.embedding <=> params.qvec) AS rnk
    FROM pool p, params
    WHERE %(w_dense)s > 0 AND p.embedding IS NOT NULL
    ORDER BY p.embedding <=> params.qvec
    LIMIT %(n)s
),
lexical AS (
    SELECT p.id, row_number() OVER (ORDER BY ts_rank_cd(p.search_tsv, params.q) DESC) AS rnk
    FROM pool p, params
    WHERE %(w_lex)s > 0 AND %(qor)s <> '' AND p.search_tsv @@ params.q
    ORDER BY ts_rank_cd(p.search_tsv, params.q) DESC
    LIMIT %(n)s
),
fused AS (
    SELECT id,
           SUM(w / (%(k)s + rnk)) AS score,
           bool_or(ch = 'dense') AS in_dense,
           bool_or(ch = 'lex')   AS in_lex
    FROM (
        SELECT id, rnk, %(w_dense)s::float AS w, 'dense' AS ch FROM dense
        UNION ALL
        SELECT id, rnk, %(w_lex)s::float AS w, 'lex' AS ch FROM lexical
    ) u
    GROUP BY id
)
SELECT c.id, c.document_id, d.source, d.external_id, d.title, c.ordinal, c.text, c.icao,
       f.score, f.in_dense, f.in_lex
FROM fused f
JOIN chunks c ON c.id = f.id
JOIN documents d ON d.id = c.document_id
ORDER BY f.score DESC, c.id
LIMIT %(limit)s
"""


def hybrid_search(
    conn: Connection[Any],
    *,
    query_text: str,
    query_vec: Sequence[float] | None,
    limit: int = 20,
    candidates: int = 40,
    rrf_k: int = 60,
    w_dense: float = 1.0,
    w_lex: float = 1.0,
    icao: str | None = None,
    source: str | None = None,
) -> list[Candidate]:
    if query_vec is None:
        w_dense = 0.0
    rows = conn.execute(_HYBRID, {
        "qvec": list(query_vec) if query_vec is not None else [0.0] * 768,
        "qor": lexical_query(query_text),
        "icao": icao, "source": source,
        "n": candidates, "k": rrf_k, "limit": limit,
        "w_dense": w_dense, "w_lex": w_lex,
    }).fetchall()
    return [Candidate(*r) for r in rows]


def stats(conn: Connection[Any]) -> dict[str, Any]:
    docs = conn.execute(
        "SELECT source, count(*) FROM documents GROUP BY source ORDER BY 1"
    ).fetchall()
    chunks = conn.execute(
        "SELECT count(*), count(embedding), coalesce(sum(chars), 0) FROM chunks"
    ).fetchone()
    assert chunks is not None
    return {
        "documents": {s: n for s, n in docs},
        "chunks": chunks[0], "embedded": chunks[1], "chars": int(chunks[2]),
    }
