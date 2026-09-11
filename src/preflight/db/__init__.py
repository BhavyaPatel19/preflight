"""Thin Postgres layer. Plain SQL, no ORM.

Retrieval in Sprint 3 is one hand-written statement fusing dense and lexical
candidates with a metadata filter — an ORM would only get in the way of that.
Keeping the rest of the data access in the same style means one idiom to read.
"""

from preflight.db.pool import close_pool, get_pool, healthcheck

__all__ = ["close_pool", "get_pool", "healthcheck"]
