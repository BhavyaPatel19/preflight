from __future__ import annotations

import json
from datetime import UTC, datetime

import structlog

from preflight.archive import archive_raw
from preflight.db import get_pool
from preflight.db import weather as wdb
from preflight.sources.aviationweather import (
    AviationWeatherClient,
    parse_metar_rows,
    parse_taf_rows,
)

log = structlog.get_logger(__name__)


async def ingest_weather(icaos: list[str], *, hours: int = 3) -> dict[str, int | str]:
    """Fetch current METARs and TAFs for ``icaos``, archive the raw rows, store the parsed."""
    client = AviationWeatherClient()
    try:
        metar_rows = await client.metar_rows(*icaos, hours=hours)
        taf_rows = await client.taf_rows(*icaos)
    finally:
        await client.aclose()

    now = datetime.now(UTC)
    tag = "aviationweather-" + "-".join(icaos)
    archive_raw("metar", tag, json.dumps(metar_rows), fetched_at=now)
    archive_raw("taf", tag, json.dumps(taf_rows), fetched_at=now)

    metars, tafs = parse_metar_rows(metar_rows), parse_taf_rows(taf_rows)
    with get_pool().connection() as conn:
        n_metar = wdb.upsert_metars(conn, metars)
        n_taf = wdb.upsert_tafs(conn, tafs)
        conn.commit()

    log.info("weather.ingested", airports=icaos, metars=n_metar, tafs=n_taf)
    return {"metars": n_metar, "tafs": n_taf, "archived_at": now.isoformat()}
