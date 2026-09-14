"""Precedent corpus: documents, chunks, and the hybrid search statement.

One SQL statement does the retrieval: a dense candidate set (HNSW, cosine) and
a lexical candidate set (tsvector, ts_rank), each filtered by the same
metadata, fused with reciprocal rank fusion. ``ts_rank`` rather than
``ts_rank_cd``: on a 34-term paraphrase query both match ~81k chunks, and the
cover-density variant took 2 s to rank them against 236 ms — measured in the
retrieval eval; see evals/retrieval/RESULTS.md. Weights of 0 switch a channel off,
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


SHORT_QUERY_TERMS = 4


def lexical_query(text: str) -> str:
    """tsquery for the lexical channel.

    Short queries (≤ 4 terms) are identifier-shaped — ``runway 28R`` — and every
    term must match, or the common word swamps the discriminating one. Long
    queries are paraphrases; OR-join them so partial matches still rank and
    ``ts_rank`` rewards the chunks that hit more of them. Both thresholds were
    set by the retrieval eval, not by taste.
    """
    terms = sorted({t.lower() for t in _TOKEN.findall(text) if len(t) > 1})
    joiner = " & " if len(terms) <= SHORT_QUERY_TERMS else " | "
    return joiner.join(terms)


# Each channel filters ``chunks`` directly so the planner can drive it from its own
# index: the HNSW scan for ``ORDER BY embedding <=> q LIMIT n`` and the GIN index for
# ``search_tsv @@ q``. An earlier version built a shared ``pool`` CTE for the filters;
# Postgres materialised it, and both channels degraded to a sequential scan and sort
# over the whole corpus (2–3 s per query instead of ~50 ms; see evals/latency).
_HYBRID = """
WITH dense AS (
    SELECT c.id, row_number() OVER (ORDER BY c.embedding <=> %(qvec)s::vector) AS rnk
    FROM chunks c
    WHERE %(w_dense)s > 0 AND c.embedding IS NOT NULL {filters}
    ORDER BY c.embedding <=> %(qvec)s::vector
    LIMIT %(n)s
),
lexical AS (
    SELECT c.id,
           row_number() OVER (ORDER BY ts_rank(c.search_tsv, to_tsquery('english', %(qor)s)) DESC
           ) AS rnk
    FROM chunks c
    WHERE %(w_lex)s > 0 AND %(qor)s <> ''
      AND c.search_tsv @@ to_tsquery('english', %(qor)s) {filters}
    ORDER BY ts_rank(c.search_tsv, to_tsquery('english', %(qor)s)) DESC
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

# HNSW is approximate, and this index (default build parameters) needs a wide search to
# match exact kNN: recall@40 against a sequential scan on 35 golden queries was 0.80 at
# ef_search=100, 0.93 at 400, 0.97 at 1000 — still ~50 ms against ~2 s for the scan.
# Iterative scan matters with filters: a plain scan stops after ``ef_search`` candidates,
# and an airport filter that admits a fraction of them returns fewer than ``n`` rows.
_HNSW_SETTINGS = "SET LOCAL hnsw.ef_search = 1000; SET LOCAL hnsw.iterative_scan = relaxed_order"


def _filters(icao: str | None, source: str | None, exclude_like: str | None,
             icao_strict: bool) -> str:
    """Only the filters actually requested, so the planner sees plain predicates."""
    parts = []
    if icao is not None:
        parts.append("AND c.icao = %(icao)s" if icao_strict
                     else "AND (c.icao = %(icao)s OR c.icao IS NULL)")
    if source is not None:
        parts.append("AND EXISTS (SELECT 1 FROM documents d WHERE d.id = c.document_id "
                     "AND d.source = %(source)s)")
    if exclude_like is not None:
        parts.append("AND c.text NOT LIKE %(exclude)s")
    return " ".join(parts)


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
    exclude_like: str | None = None,
    icao_strict: bool = False,
) -> list[Candidate]:
    """``exclude_like`` drops chunks matching a SQL LIKE pattern — the eval uses it to hide
    synopsis-bearing chunks so a synopsis query has to find the narrative. ``icao_strict``
    makes the airport filter exclude chunks with no airport (by default they are admitted,
    since an unknown airport is not a different airport)."""
    if query_vec is None:
        w_dense = 0.0
    sql = _HYBRID.format(filters=_filters(icao, source, exclude_like, icao_strict))
    with conn.transaction():
        conn.execute(_HNSW_SETTINGS)
        rows = conn.execute(sql, {
            "qvec": list(query_vec) if query_vec is not None else [0.0] * 768,
            "qor": lexical_query(query_text),
            "icao": icao, "source": source, "exclude": exclude_like,
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
