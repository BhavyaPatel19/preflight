from __future__ import annotations

import structlog

from preflight.db import get_pool
from preflight.db import weather as wdb
from preflight.sources.aviationweather import AviationWeatherClient

log = structlog.get_logger(__name__)


async def ingest_weather(icaos: list[str], *, hours: int = 3) -> dict[str, int]:
    """Fetch current METARs and TAFs for ``icaos`` and store them."""
    client = AviationWeatherClient()
    try:
        metars = await client.metars(*icaos, hours=hours)
        tafs = await client.tafs(*icaos)
    finally:
        await client.aclose()

    with get_pool().connection() as conn:
        n_metar = wdb.upsert_metars(conn, metars)
        n_taf = wdb.upsert_tafs(conn, tafs)
        conn.commit()

    log.info("weather.ingested", airports=icaos, metars=n_metar, tafs=n_taf)
    return {"metars": n_metar, "tafs": n_taf}
