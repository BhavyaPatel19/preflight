from __future__ import annotations

from functools import lru_cache
from typing import Any

from pgvector.psycopg import register_vector
from psycopg import Connection
from psycopg_pool import ConnectionPool

from preflight.config import settings


@lru_cache
def get_pool() -> ConnectionPool:
    """Process-wide pool. Lazily opened on first use; small on purpose for now."""
    return ConnectionPool(
        conninfo=settings().database_url,
        min_size=1,
        max_size=8,
        open=True,
        kwargs={"autocommit": False},
        configure=_configure,
    )


def _configure(conn: Connection[Any]) -> None:
    register_vector(conn)


def close_pool() -> None:
    """Close the pool if one was opened. Safe to call when it was not."""
    if get_pool.cache_info().currsize:
        get_pool().close()
        get_pool.cache_clear()


def healthcheck() -> dict[str, str | bool]:
    """Round-trip the database and confirm pgvector is present."""
    with get_pool().connection() as conn:
        version = conn.execute("SELECT version()").fetchone()
        vec = conn.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
    return {
        "ok": True,
        "postgres": (version[0].split(",")[0] if version else "?"),
        "pgvector": vec[0] if vec else False,
    }
