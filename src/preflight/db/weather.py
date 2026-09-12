"""Persistence for weather reports. The raw string is the citation; keep it whole."""

from __future__ import annotations

from datetime import datetime
from typing import Any, NamedTuple

from psycopg import Connection
from psycopg.types.json import Jsonb

from preflight.sources.aviationweather import Metar, Taf

_UPSERT = """
INSERT INTO weather_reports (icao, kind, issued_at, valid_from, valid_to, raw, parsed, fetched_at)
VALUES (%s, %s, %s, %s, %s, %s, %s, now())
ON CONFLICT (icao, kind, issued_at) DO UPDATE SET
    valid_from = EXCLUDED.valid_from, valid_to = EXCLUDED.valid_to,
    raw = EXCLUDED.raw, parsed = EXCLUDED.parsed, fetched_at = now()
"""

_LATEST = """
SELECT raw, parsed, issued_at, valid_from, valid_to FROM weather_reports
WHERE icao = %s AND kind = %s ORDER BY issued_at DESC LIMIT 1
"""


class WeatherRow(NamedTuple):
    raw: str
    parsed: dict[str, Any]
    issued_at: datetime
    valid_from: datetime | None
    valid_to: datetime | None


def upsert_metars(conn: Connection[Any], metars: list[Metar]) -> int:
    for m in metars:
        parsed = m.model_dump(mode="json", exclude={"icao", "raw", "observed_at"})
        conn.execute(_UPSERT, (m.icao, "METAR", m.observed_at, None, None, m.raw, Jsonb(parsed)))
    return len(metars)


def upsert_tafs(conn: Connection[Any], tafs: list[Taf]) -> int:
    for t in tafs:
        conn.execute(
            _UPSERT, (t.icao, "TAF", t.issued_at, t.valid_from, t.valid_to, t.raw, Jsonb({}))
        )
    return len(tafs)


def latest(conn: Connection[Any], icao: str, kind: str) -> WeatherRow | None:
    row = conn.execute(_LATEST, (icao, kind)).fetchone()
    return WeatherRow(*row) if row else None
