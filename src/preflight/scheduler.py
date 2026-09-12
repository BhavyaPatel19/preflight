"""Scheduled ingestion.

An in-process scheduler that runs the ingest jobs on an interval and records
every run. Weather is fetched hourly for the watchlist; the NOTAM job runs on
the same cadence and simply reports "skipped" until a source is configured —
so the day a token lands, the archive starts filling with no code change.

Runs as ``preflight schedule`` or as the ``scheduler`` service in compose.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from preflight.config import settings
from preflight.db import get_pool
from preflight.db.runs import Status, record_run
from preflight.sources.notams import NasaDipSource, NotamSource, SourceUnavailable

log = structlog.get_logger(__name__)

JobResult = dict[str, Any]


async def _run(kind: str, source: str, job: Callable[[], Awaitable[JobResult]]) -> Status:
    """Execute one job, log it, and record the outcome. Never raises into the scheduler."""
    started = datetime.now(UTC)
    status: Status
    counts: JobResult = {}
    error: str | None = None
    try:
        counts = await job()
        status = "ok"
    except SourceUnavailable as e:
        status, error = "skipped", str(e)
        log.info("ingest.skipped", kind=kind, source=source, reason=error)
    except Exception as e:  # noqa: BLE001 — a failed fetch must not kill the scheduler
        status, error = "error", f"{type(e).__name__}: {e}"
        log.error("ingest.failed", kind=kind, source=source, error=error)
    finished = datetime.now(UTC)

    with get_pool().connection() as conn:
        record_run(
            conn, kind=kind, source=source, started_at=started, finished_at=finished,
            status=status, counts={k: v for k, v in counts.items() if isinstance(v, int)},
            error=error,
        )
        conn.commit()
    if status == "ok":
        log.info("ingest.ok", kind=kind, source=source, **counts)
    return status


async def weather_job(icaos: list[str] | None = None) -> Status:
    from preflight.ingest.weather import ingest_weather

    airports = icaos or settings().watchlist
    return await _run("weather", "aviationweather", lambda: ingest_weather(airports, hours=2))


def _notam_source() -> NotamSource:
    s = settings()
    return NasaDipSource(s.nasa_dip_base_url, s.nasa_dip_token)


async def notam_job(icaos: list[str] | None = None, source: NotamSource | None = None) -> Status:
    from preflight.ingest.notams import ingest_notams

    src = source or _notam_source()
    airports = icaos or settings().watchlist
    return await _run("notams", src.name, lambda: ingest_notams(src, airports))


def build_scheduler() -> AsyncIOScheduler:
    """Weather at :05 past each hour (METARs issue at ~:53); NOTAMs at :10."""
    sched = AsyncIOScheduler(timezone="UTC")
    sched.add_job(weather_job, CronTrigger(minute=5), id="weather", misfire_grace_time=600,
                  coalesce=True, max_instances=1)
    sched.add_job(notam_job, CronTrigger(minute=10), id="notams", misfire_grace_time=600,
                  coalesce=True, max_instances=1)
    return sched


async def run_forever(*, run_now: bool = True) -> None:
    sched = build_scheduler()
    if run_now:
        await weather_job()
        await notam_job()
    sched.start()
    log.info("scheduler.started", watchlist=settings().watchlist,
             jobs=[j.id for j in sched.get_jobs()])
    try:
        await asyncio.Event().wait()
    finally:
        sched.shutdown(wait=False)
