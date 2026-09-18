"""Iowa State ASOS archive client: request shape, window filter, archive, politeness."""

from datetime import UTC, datetime, timedelta

import httpx
import pytest
import respx

from preflight.sources import iem
from preflight.sources.notams import SourceUnavailable

CSV = """station,valid,metar
TWF,2026-05-14 16:56,KTWF 141656Z 29018G26KT 10SM SCT060 17/M02 A2998 RMK AO2
TWF,2026-05-14 17:56,KTWF 141756Z 30025G34KT 3SM HZ BKN029 19/M03 A2994 RMK AO2
TWF,2026-05-14 19:56,KTWF 141956Z 31020G30KT 10SM SCT050 20/M04 A2992 RMK AO2
"""


def test_station_ids():
    assert iem.iem_station("KTWF") == "TWF" and iem.iem_station("PANC") == "PANC"
    assert iem.iem_station("EGLL") == "EGLL"


@respx.mock
def test_fetch_parses_window_and_archives(tmp_path, monkeypatch):
    from preflight import config

    monkeypatch.setattr(config.settings(), "archive_dir", tmp_path)
    route = respx.get(iem.BASE).mock(return_value=httpx.Response(200, text=CSV))
    slept: list[float] = []
    src = iem.IemAsos(client=httpx.Client(), sleep=slept.append, min_interval_s=1.0)
    end = datetime(2026, 5, 14, 18, 30, tzinfo=UTC)
    got = src.fetch_metars("KTWF", end - timedelta(hours=3), end)
    assert route.called and route.calls[0].request.url.params["station"] == "TWF"
    assert [m.observed_at.hour for m in got] == [16, 17]          # 19:56 is after the window
    assert got[1].gust_kt == 34 and got[1].flight_category == "MVFR" and got[1].icao == "KTWF"
    archived = list((tmp_path / "weather").rglob("*iem-asos-KTWF*"))
    assert len(archived) == 1 and "KTWF 141756Z" in archived[0].read_text()
    # A second call within the interval waits.
    src.fetch_metars("KTWF", end - timedelta(hours=3), end)
    assert slept and 0 < slept[0] <= 1.0


@respx.mock
def test_rate_limit_backs_off_then_succeeds():
    route = respx.get(iem.BASE).mock(side_effect=[
        httpx.Response(429, headers={"Retry-After": "7"}), httpx.Response(503),
        httpx.Response(200, text=CSV)])
    slept: list[float] = []
    src = iem.IemAsos(client=httpx.Client(), archive=False, sleep=slept.append, min_interval_s=0)
    got = src.fetch_metars("KTWF", datetime(2026, 5, 14, tzinfo=UTC),
                           datetime(2026, 5, 15, tzinfo=UTC))
    assert len(got) == 3 and route.call_count == 3
    assert slept == [7.0, 90.0]                 # Retry-After honoured, then the escalating default


@respx.mock
def test_persistent_failure_is_source_unavailable():
    respx.get(iem.BASE).mock(return_value=httpx.Response(503))
    src = iem.IemAsos(client=httpx.Client(), archive=False, sleep=lambda s: None, retries=1,
                      min_interval_s=0)
    with pytest.raises(SourceUnavailable):
        src.fetch_metars("KTWF", datetime(2026, 1, 1, tzinfo=UTC), datetime(2026, 1, 2, tzinfo=UTC))
