from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import pytest

from preflight.config import DEFAULT_WATCHLIST, Settings
from preflight.db.runs import last_runs, record_run
from preflight.scheduler import _run, build_scheduler, notam_job
from preflight.sources.notams import RawNotam, SourceUnavailable

T = datetime(2026, 9, 12, 6, 0, tzinfo=UTC)


# ---------------------------------------------------------------- config

def test_watchlist_csv_from_environment(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_WATCHLIST", " ksfo, kjfk ,,kbos ")
    assert Settings().watchlist == ["KSFO", "KJFK", "KBOS"]


def test_empty_watchlist_means_default(monkeypatch):
    monkeypatch.setenv("PREFLIGHT_WATCHLIST", "")
    assert Settings().watchlist == DEFAULT_WATCHLIST and len(DEFAULT_WATCHLIST) == 30


# ---------------------------------------------------------------- run log

@pytest.mark.db
def test_last_runs_returns_most_recent_per_source(db):
    for i, status in enumerate(["ok", "error", "ok"]):
        record_run(db, kind="weather", source="t-src", started_at=T + timedelta(hours=i),
                   finished_at=T + timedelta(hours=i, minutes=1), status=status,
                   counts={"metars": i})
    record_run(db, kind="notams", source="t-src", started_at=T, finished_at=T,
               status="skipped", error="no token")
    rows = {(r.kind, r.source): r for r in last_runs(db)}
    assert rows[("weather", "t-src")].counts == {"metars": 2}
    assert rows[("weather", "t-src")].status == "ok"
    assert rows[("notams", "t-src")].error == "no token"


# ---------------------------------------------------------------- job wrapper

class _Pool:
    def __init__(self, conn):
        self._conn = conn

    @contextmanager
    def connection(self):
        yield self._conn


@pytest.fixture
def pool(db, monkeypatch):
    # Route the wrapper's run-log writes through the rolled-back test connection.
    monkeypatch.setattr("preflight.scheduler.get_pool", lambda: _Pool(db))
    monkeypatch.setattr(db, "commit", lambda: None)
    return db


@pytest.mark.db
async def test_ok_run_records_int_counts_only(pool):
    async def job():
        return {"metars": 5, "tafs": 2, "archived_at": "2026-…"}

    assert await _run("weather", "fake", job) == "ok"
    row = next(r for r in last_runs(pool) if r.source == "fake")
    assert row.status == "ok" and row.counts == {"metars": 5, "tafs": 2} and row.error is None


@pytest.mark.db
async def test_unavailable_source_is_skipped_not_failed(pool):
    async def job():
        raise SourceUnavailable("no token yet")

    assert await _run("notams", "fake", job) == "skipped"
    row = next(r for r in last_runs(pool) if r.source == "fake")
    assert row.status == "skipped" and row.error == "no token yet"


@pytest.mark.db
async def test_unexpected_error_is_recorded_and_swallowed(pool):
    async def job():
        raise RuntimeError("upstream 503")

    assert await _run("weather", "fake", job) == "error"     # did not raise
    row = next(r for r in last_runs(pool) if r.source == "fake")
    assert row.status == "error" and row.error == "RuntimeError: upstream 503"


@pytest.mark.db
async def test_notam_job_uses_injected_source(pool, tmp_path, monkeypatch):
    from preflight.config import settings

    monkeypatch.setattr(settings(), "archive_dir", tmp_path)
    monkeypatch.setattr("preflight.ingest.notams.get_pool", lambda: _Pool(pool))

    class Src:
        name = "injected"

        async def fetch(self, icaos):
            return [RawNotam(text="A0001/26 NOTAMN\nA) KZZY B) 2609100000 C) 2609120000\n"
                                  "E) TWY Q CLSD.", source=self.name, fetched_at=T)]

    assert await notam_job(["KZZY"], source=Src()) == "ok"
    row = next(r for r in last_runs(pool) if r.source == "injected")
    assert row.counts["stored"] == 1
    pool.execute("DELETE FROM notams WHERE icao = 'KZZY'")


# ---------------------------------------------------------------- schedule

def test_scheduler_has_hourly_weather_and_notam_jobs():
    sched = build_scheduler()
    jobs = {j.id: j for j in sched.get_jobs()}
    assert set(jobs) == {"weather", "notams"}
    trig = jobs["weather"].trigger
    assert str(trig.fields[trig.FIELD_NAMES.index("minute")]) == "5"
    assert jobs["weather"].max_instances == 1 and jobs["weather"].coalesce
