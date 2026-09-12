"""Client for the aviationweather.gov data API (METAR / TAF).

No key required. Responses are returned raw alongside a few parsed fields; the
raw string is what gets cited in a briefing, so it is always preserved.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field

from preflight.config import settings


class Metar(BaseModel):
    model_config = ConfigDict(frozen=True)

    icao: str
    observed_at: datetime
    raw: str
    flight_category: str | None = Field(default=None, description="VFR / MVFR / IFR / LIFR")
    wind_dir: int | None = None
    wind_kt: int | None = None
    gust_kt: int | None = None
    visibility_sm: float | None = None
    temp_c: float | None = None
    dewpoint_c: float | None = None
    altimeter_hpa: float | None = None
    wx: str | None = Field(default=None, description="Present-weather string, e.g. '-RA BR'")
    ceiling_ft: int | None = None


class Taf(BaseModel):
    model_config = ConfigDict(frozen=True)

    icao: str
    issued_at: datetime
    valid_from: datetime
    valid_to: datetime
    raw: str


def _ts(value: Any) -> datetime | None:
    """aviationweather.gov mixes epoch seconds and ISO strings across endpoints."""
    if value is None:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(value, tz=UTC)
    if isinstance(value, str):
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    return None


def _visibility(value: Any) -> float | None:
    # "10+" is the API's way of saying "at least ten statute miles".
    if value is None:
        return None
    if isinstance(value, str):
        value = value.rstrip("+")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ceiling(clouds: list[dict[str, Any]] | None) -> int | None:
    """Ceiling is the lowest broken or overcast layer."""
    if not clouds:
        return None
    bases: list[int] = [
        c["base"] for c in clouds
        if c.get("cover") in {"BKN", "OVC", "OVX"} and isinstance(c.get("base"), int)
    ]
    return min(bases) if bases else None


class AviationWeatherClient:
    def __init__(self, client: httpx.AsyncClient | None = None, base: str | None = None):
        self._base = (base or settings().aviationweather_base).rstrip("/")
        self._client = client or httpx.AsyncClient(timeout=15.0)

    async def metar_rows(self, *icaos: str, hours: int = 3) -> list[dict[str, Any]]:
        """Raw API rows — what the archive keeps."""
        params = {"ids": ",".join(icaos), "format": "json", "hours": str(hours)}
        r = await self._client.get(f"{self._base}/metar", params=params)
        r.raise_for_status()
        rows: list[dict[str, Any]] = r.json()
        return rows

    async def taf_rows(self, *icaos: str) -> list[dict[str, Any]]:
        params = {"ids": ",".join(icaos), "format": "json"}
        r = await self._client.get(f"{self._base}/taf", params=params)
        r.raise_for_status()
        rows: list[dict[str, Any]] = r.json()
        return rows

    async def metars(self, *icaos: str, hours: int = 3) -> list[Metar]:
        return parse_metar_rows(await self.metar_rows(*icaos, hours=hours))

    async def tafs(self, *icaos: str) -> list[Taf]:
        return parse_taf_rows(await self.taf_rows(*icaos))

    async def aclose(self) -> None:
        await self._client.aclose()


def parse_metar_rows(rows: list[dict[str, Any]]) -> list[Metar]:
    out: list[Metar] = []
    for row in rows:
        observed = _ts(row.get("reportTime") or row.get("obsTime"))
        if observed is None:
            continue
        out.append(Metar(
            icao=row["icaoId"],
            observed_at=observed,
            raw=row.get("rawOb", ""),
            flight_category=row.get("fltCat"),
            wind_dir=row.get("wdir") if isinstance(row.get("wdir"), int) else None,
            wind_kt=row.get("wspd"),
            gust_kt=row.get("wgst"),
            visibility_sm=_visibility(row.get("visib")),
            temp_c=row.get("temp"),
            dewpoint_c=row.get("dewp"),
            altimeter_hpa=row.get("altim"),
            wx=row.get("wxString"),
            ceiling_ft=_ceiling(row.get("clouds")),
        ))
    return out


def parse_taf_rows(rows: list[dict[str, Any]]) -> list[Taf]:
    out: list[Taf] = []
    for row in rows:
        issued = _ts(row.get("issueTime"))
        vfrom = _ts(row.get("validTimeFrom"))
        vto = _ts(row.get("validTimeTo"))
        if not (issued and vfrom and vto):
            continue
        out.append(Taf(
            icao=row["icaoId"], issued_at=issued, valid_from=vfrom, valid_to=vto,
            raw=row.get("rawTAF", ""),
        ))
    return out
