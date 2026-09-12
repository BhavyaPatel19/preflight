"""Ingest run log."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, NamedTuple

from psycopg import Connection
from psycopg.types.json import Jsonb

Status = Literal["ok", "skipped", "error"]


class RunRow(NamedTuple):
    kind: str
    source: str
    started_at: datetime
    finished_at: datetime
    status: str
    counts: dict[str, Any]
    error: str | None


def record_run(
    conn: Connection[Any],
    *,
    kind: str,
    source: str,
    started_at: datetime,
    finished_at: datetime,
    status: Status,
    counts: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO ingest_runs (kind, source, started_at, finished_at, status, counts, error) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (kind, source, started_at, finished_at, status, Jsonb(counts or {}), error),
    )


def last_runs(conn: Connection[Any]) -> list[RunRow]:
    """Most recent run per (kind, source)."""
    rows = conn.execute(
        """
        SELECT DISTINCT ON (kind, source)
               kind, source, started_at, finished_at, status, counts, error
        FROM ingest_runs
        ORDER BY kind, source, started_at DESC
        """
    ).fetchall()
    return [RunRow(*r) for r in rows]
