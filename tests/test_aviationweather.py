"""aviationweather.gov client.

Fixtures mirror the real response shape observed on 2026-09-11: ISO ``reportTime``
alongside epoch ``obsTime``, ``"10+"`` visibility, null gusts, mixed cloud layers.
The live test at the bottom is opt-in (``pytest -m live``).
"""

from datetime import UTC, datetime

import httpx
import pytest
import respx

from preflight.sources.aviationweather import AviationWeatherClient, _ceiling, _ts, _visibility

BASE = "https://aviationweather.gov/api/data"

METAR_ROW = {
    "icaoId": "KSFO",
    "reportTime": "2026-09-11T02:00:00.000Z",
    "obsTime": 1789091760,
    "temp": 17.8, "dewp": 15, "wdir": 320, "wspd": 16, "wgst": None,
    "visib": "10+", "altim": 1013, "wxString": None, "fltCat": "VFR",
    "clouds": [{"cover": "FEW", "base": 200}, {"cover": "FEW", "base": 18000},
               {"cover": "BKN", "base": 20000}],
    "rawOb": "METAR KSFO 110156Z 32016KT 10SM FEW002 FEW180 BKN200 18/15 A2991 RMK AO2",
}

TAF_ROW = {
    "icaoId": "KSFO",
    "issueTime": "2026-09-10T23:26:00.000Z",
    "validTimeFrom": 1789084800,
    "validTimeTo": 1789192800,
    "rawTAF": "TAF KSFO 102326Z 1100/1206 32013KT P6SM FEW005 SCT200 FM111200 25008KT P6SM BKN010",
}


@pytest.fixture
def client():
    return AviationWeatherClient(client=httpx.AsyncClient(), base=BASE)


# ---------------------------------------------------------------- helpers

def test_ts_accepts_iso_and_epoch():
    assert _ts("2026-09-11T02:00:00.000Z") == datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    assert _ts(1789084800) == datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
    assert _ts(None) is None
    assert _ts({"weird": 1}) is None


def test_visibility_strips_plus():
    assert _visibility("10+") == 10.0
    assert _visibility(2.5) == 2.5
    assert _visibility(None) is None
    assert _visibility("garbage") is None


def test_ceiling_is_lowest_broken_or_overcast():
    assert _ceiling(METAR_ROW["clouds"]) == 20000            # FEW layers ignored
    assert _ceiling([{"cover": "OVC", "base": 800}, {"cover": "BKN", "base": 1500}]) == 800
    assert _ceiling([{"cover": "SCT", "base": 3000}]) is None
    assert _ceiling([]) is None and _ceiling(None) is None


# ---------------------------------------------------------------- METAR

@respx.mock
@pytest.mark.asyncio
async def test_metars_parse_real_shape(client):
    route = respx.get(f"{BASE}/metar").mock(return_value=httpx.Response(200, json=[METAR_ROW]))
    out = await client.metars("KSFO", hours=1)

    assert route.called
    assert route.calls[0].request.url.params["ids"] == "KSFO"
    assert route.calls[0].request.url.params["hours"] == "1"

    assert len(out) == 1
    m = out[0]
    assert m.icao == "KSFO"
    assert m.observed_at == datetime(2026, 9, 11, 2, 0, tzinfo=UTC)
    assert m.flight_category == "VFR"
    assert m.wind_dir == 320 and m.wind_kt == 16 and m.gust_kt is None
    assert m.visibility_sm == 10.0
    assert m.ceiling_ft == 20000
    assert m.temp_c == 17.8 and m.dewpoint_c == 15
    assert m.raw.startswith("METAR KSFO 110156Z")     # raw always preserved for citation


@respx.mock
@pytest.mark.asyncio
async def test_metars_multiple_stations_joined(client):
    route = respx.get(f"{BASE}/metar").mock(return_value=httpx.Response(200, json=[]))
    await client.metars("KSFO", "KJFK")
    assert route.calls[0].request.url.params["ids"] == "KSFO,KJFK"


@respx.mock
@pytest.mark.asyncio
async def test_metars_skip_rows_without_timestamp(client):
    bad = {**METAR_ROW, "reportTime": None, "obsTime": None}
    respx.get(f"{BASE}/metar").mock(return_value=httpx.Response(200, json=[bad, METAR_ROW]))
    out = await client.metars("KSFO")
    assert len(out) == 1


@respx.mock
@pytest.mark.asyncio
async def test_metars_fall_back_to_epoch_obstime(client):
    row = {**METAR_ROW, "reportTime": None}
    respx.get(f"{BASE}/metar").mock(return_value=httpx.Response(200, json=[row]))
    out = await client.metars("KSFO")
    assert out[0].observed_at == datetime.fromtimestamp(1789091760, tz=UTC)


@respx.mock
@pytest.mark.asyncio
async def test_variable_wind_direction_is_none(client):
    row = {**METAR_ROW, "wdir": "VRB"}
    respx.get(f"{BASE}/metar").mock(return_value=httpx.Response(200, json=[row]))
    out = await client.metars("KSFO")
    assert out[0].wind_dir is None


# ---------------------------------------------------------------- TAF

@respx.mock
@pytest.mark.asyncio
async def test_tafs_parse_mixed_iso_and_epoch(client):
    respx.get(f"{BASE}/taf").mock(return_value=httpx.Response(200, json=[TAF_ROW]))
    out = await client.tafs("KSFO")
    assert len(out) == 1
    t = out[0]
    assert t.issued_at == datetime(2026, 9, 10, 23, 26, tzinfo=UTC)
    assert t.valid_from == datetime(2026, 9, 11, 0, 0, tzinfo=UTC)
    assert t.valid_to == datetime(2026, 9, 12, 6, 0, tzinfo=UTC)
    assert t.raw.startswith("TAF KSFO")


@respx.mock
@pytest.mark.asyncio
async def test_tafs_skip_incomplete_validity(client):
    respx.get(f"{BASE}/taf").mock(
        return_value=httpx.Response(200, json=[{**TAF_ROW, "validTimeTo": None}])
    )
    assert await client.tafs("KSFO") == []


# ---------------------------------------------------------------- errors

@respx.mock
@pytest.mark.asyncio
async def test_http_error_propagates(client):
    respx.get(f"{BASE}/metar").mock(return_value=httpx.Response(503))
    with pytest.raises(httpx.HTTPStatusError):
        await client.metars("KSFO")


# ---------------------------------------------------------------- live

@pytest.mark.live
@pytest.mark.asyncio
async def test_live_ksfo_metar_and_taf():
    """Hits the real API. Run with ``pytest -m live``."""
    c = AviationWeatherClient()
    try:
        metars = await c.metars("KSFO", hours=2)
        tafs = await c.tafs("KSFO")
    finally:
        await c.aclose()
    assert metars and metars[0].icao == "KSFO" and metars[0].raw
    assert tafs and tafs[0].icao == "KSFO" and tafs[0].valid_to > tafs[0].valid_from
