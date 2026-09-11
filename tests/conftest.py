import psycopg
import pytest

from preflight.config import settings


@pytest.fixture(scope="session")
def _db_reachable() -> bool:
    try:
        with psycopg.connect(settings().database_url, connect_timeout=2):
            return True
    except psycopg.OperationalError:
        return False


@pytest.fixture
def db(_db_reachable):
    """A connection whose work is rolled back after each test.

    Skips (rather than fails) when no database is listening, so the pure
    tests stay runnable on a laptop with nothing else installed.
    """
    if not _db_reachable:
        pytest.skip("no database at DATABASE_URL — `make up` to run these")
    with psycopg.connect(settings().database_url, autocommit=False) as conn:
        yield conn
        conn.rollback()
