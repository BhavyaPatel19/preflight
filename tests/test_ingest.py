"""Ingestion pipeline. The decode step is pure; the end-to-end test needs the database."""

from datetime import UTC, datetime

import pytest

from preflight.decode.notam import DEMO_NOTAMS
from preflight.ingest.notams import decode_many, ingest_notams
from preflight.sources.notams import RawNotam


def test_decode_many_separates_failures_from_successes():
    ok, failed = decode_many(DEMO_NOTAMS + ["this is not a notam"])
    assert len(ok) == 3 and failed == ["this is not a notam"]


class _FakeSource:
    name = "fake"

    def __init__(self, texts):
        self.texts = texts

    async def fetch(self, icaos=()):
        now = datetime.now(UTC)
        return [RawNotam(text=t, source=self.name, fetched_at=now) for t in self.texts]


class _Pool:
    """Routes the job's writes through the test's rolled-back connection."""

    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        from contextlib import nullcontext

        return nullcontext(self._conn)


@pytest.mark.db
async def test_pipeline_archives_then_stores(db, tmp_path, monkeypatch):
    """End to end against the real database, with synthetic airports and a temp archive.

    The job must run through the test connection: through the real pool it would commit,
    and its synthetic NOTAMs must not share ids with the bundled samples — an earlier
    version of this test overwrote and then deleted the real demo rows on every run.
    """
    from preflight.config import settings
    from preflight.db import notams as ndb

    monkeypatch.setattr(settings(), "archive_dir", tmp_path)
    monkeypatch.setattr("preflight.ingest.notams.get_pool", lambda: _Pool(db))
    monkeypatch.setattr(db, "commit", lambda: None)
    swapped = [t.replace("KSFO", "KZZY").replace("KJFK", "KZZX").replace("SFO", "ZZY")
                .replace("A1477/26", "Z1477/26").replace("A0912/26", "Z0912/26")
               for t in DEMO_NOTAMS]

    result = await ingest_notams(_FakeSource(swapped + ["garbage"]))

    assert result["fetched"] == 4 and result["stored"] == 3 and result["unparseable"] == 1
    archived = tmp_path / "notams"
    files = list(archived.rglob("*.txt"))
    assert len(files) == 1 and "fake" in files[0].name
    assert "garbage" in files[0].read_text()          # archive keeps what decode rejected

    found = ndb.active_at(db, "KZZY", datetime(2026, 9, 11, 2, 0, tzinfo=UTC))
    assert {r.id for r in found} >= {"Z1477/26", "!ZZY 09/142"}
