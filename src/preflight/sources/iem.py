"""Historical METARs and TAFs from the Iowa Environmental Mesonet archives (Iowa State).

Public, no account, and scripted access is what the service is for — IEM
publishes its own download scripts for this endpoint. Used by the time-travel
briefing eval to backfill the weather at an NTSB event's airport, which turns
"coverage: 0" into a measured number for the weather-implicated cases. TAFs come from the
IEM's archive of NWS text products (``TAFxxx``, back to 1996), as the raw bulletin, so a briefing
can quote the forecaster's words. Every
response is archived raw before it is decoded (ADR 0002), and requests are
spaced out: this is someone else's server.
"""

from __future__ import annotations

import csv
import io
import re
import time
from collections.abc import Callable
from datetime import UTC, datetime

import httpx

from preflight.archive import archive_raw
from preflight.decode.taf import TafParseError, taf_header
from preflight.sources.aviationweather import Metar, Taf
from preflight.sources.metar_text import parse_metar
from preflight.sources.notams import SourceUnavailable

BASE = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
AFOS = "https://mesonet.agron.iastate.edu/cgi-bin/afos/retrieve.py"
# One TAF inside a text product: from "TAF" (optionally AMD/COR) to the terminating "=".
_TAF_TEXT = re.compile(r"TAF(?:\s+(?:AMD|COR))?\s+[A-Z0-9]{4}\s+\d{6}Z\s.*?=", re.S)


def iem_station(icao: str) -> str:
    """IEM keys CONUS ASOS sites by their 3-letter identifier (KSFO → SFO); Alaska, Hawaii
    and everywhere else keep the 4-letter ICAO code."""
    return icao[1:] if len(icao) == 4 and icao.startswith("K") else icao


class IemAsos:
    """One request every ``min_interval_s`` at most, and a 429/503 is a signal to back off
    (``Retry-After`` honoured, otherwise 30 s, 90 s, 270 s) — not to retry harder."""

    RETRY_STATUSES = frozenset({429, 502, 503, 504})

    def __init__(self, *, client: httpx.Client | None = None, min_interval_s: float = 4.0,
                 archive: bool = True, sleep: Callable[[float], None] = time.sleep,
                 retries: int = 3):
        self._client = client or httpx.Client(timeout=60.0, headers={
            "User-Agent": "preflight (research; github.com/BhavyaPatel19/preflight)"})
        self.min_interval_s = min_interval_s
        self.archive = archive
        self._sleep = sleep
        self._last = 0.0
        self.retries = retries

    def _get(self, params: dict[str, str | int], url: str = BASE) -> httpx.Response:
        backoff = 30.0
        for attempt in range(self.retries + 1):
            wait = self.min_interval_s - (time.monotonic() - self._last)
            if wait > 0:
                self._sleep(wait)
            try:
                r = self._client.get(url, params=params)
            finally:
                self._last = time.monotonic()
            if r.status_code in self.RETRY_STATUSES and attempt < self.retries:
                retry_after = r.headers.get("Retry-After")
                pause = float(retry_after) if retry_after and retry_after.isdigit() else backoff
                self._sleep(pause)
                backoff *= 3
                continue
            r.raise_for_status()
            return r
        raise AssertionError("unreachable")

    def fetch_metars(self, icao: str, start: datetime, end: datetime) -> list[Metar]:
        """Every METAR the archive holds for ``icao`` in [start, end], oldest first."""
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        params: dict[str, str | int] = {
            "station": iem_station(icao), "data": "metar",
            "year1": start.year, "month1": start.month, "day1": start.day,
            "year2": end.year, "month2": end.month, "day2": end.day,
            "tz": "Etc/UTC", "format": "onlycomma", "latlon": "no", "elev": "no",
            "missing": "M", "trace": "T", "direct": "no",
        }
        try:
            r = self._get(params)
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"IEM ASOS: {e}") from e
        if self.archive:
            archive_raw("weather", f"iem-asos-{icao}", r.text)
        out: list[Metar] = []
        for row in csv.DictReader(io.StringIO(r.text)):
            raw = (row.get("metar") or "").strip()
            when = (row.get("valid") or "").strip()
            if not raw or not when:
                continue
            observed = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=UTC)
            if not start <= observed <= end:
                continue
            out.append(parse_metar(raw, icao=icao, observed_at=observed))
        return out

    def fetch_tafs(self, icao: str, start: datetime, end: datetime) -> list[Taf]:
        """Every TAF for ``icao`` issued in [start, end], oldest first, as the raw text."""
        start, end = start.astimezone(UTC), end.astimezone(UTC)
        params: dict[str, str | int] = {
            "pil": f"TAF{icao[-3:]}", "fmt": "text", "limit": 9999, "order": "asc",
            "sdate": f"{start:%Y-%m-%dT%H:%M}Z", "edate": f"{end:%Y-%m-%dT%H:%M}Z",
        }
        try:
            r = self._get(params, url=AFOS)
        except httpx.HTTPError as e:
            raise SourceUnavailable(f"IEM AFOS: {e}") from e
        if self.archive:
            archive_raw("weather", f"iem-taf-{icao}", r.text)
        out: dict[datetime, Taf] = {}
        for m in _TAF_TEXT.finditer(r.text):
            raw = " ".join(m.group(0).split())
            try:
                station, issued, vfrom, vto = taf_header(raw, ref=end)
            except TafParseError:
                continue
            if station != icao or not start <= issued <= end:
                continue
            out[issued] = Taf(icao=icao, issued_at=issued, valid_from=vfrom, valid_to=vto,
                              raw=raw)            # an amendment at the same minute wins
        return [out[k] for k in sorted(out)]
