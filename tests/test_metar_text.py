"""Raw METAR decoding — the groups the briefing's rules read, and the FAA flight category."""

from datetime import UTC, datetime

import pytest

from preflight.sources.metar_text import flight_category, parse_metar

T = datetime(2026, 5, 14, 0, 1, tzinfo=UTC)


def _p(raw):
    return parse_metar(raw, icao=raw[:4], observed_at=T)


def test_gusty_wind_haze_and_ceiling():
    m = _p("KTWF 140001Z 30025G40KT 3SM HZ BKN029 OVC037 19/M03 A2994 RMK AO2 PK WND 30040/2354")
    assert (m.wind_dir, m.wind_kt, m.gust_kt) == (300, 25, 40)
    assert m.visibility_sm == 3.0 and m.ceiling_ft == 2900 and m.wx == "HZ"
    assert (m.temp_c, m.dewpoint_c) == (19.0, -3.0) and m.altimeter_hpa == 1013.9
    assert m.flight_category == "MVFR" and m.raw.startswith("KTWF")


def test_mixed_fraction_visibility_rain_and_low_ceiling_is_lifr():
    m = _p("KJFK 121251Z 04012G22KT 2 1/2SM -RA BR OVC004 08/07 A2990 RMK AO2")
    assert m.visibility_sm == 2.5 and m.ceiling_ft == 400 and m.wx == "-RA BR"
    assert m.flight_category == "LIFR"


def test_less_than_quarter_mile_fog_vertical_visibility():
    m = _p("KBOS 010154Z VRB03KT M1/4SM FG VV001 12/12 A3011 RMK AO2")
    assert m.wind_dir is None and m.wind_kt == 3 and m.visibility_sm == 0.0
    assert m.ceiling_ft == 100 and m.flight_category == "LIFR"


def test_clear_calm_vfr_and_metric_visibility():
    m = _p("KDEN 010053Z 00000KT 10SM CLR 22/M01 A3021 RMK AO2 SLP180")
    assert m.wind_kt == 0 and m.ceiling_ft is None and m.flight_category == "VFR"
    e = _p("EGLL 121250Z 24008KT 9999 FEW030 15/08 Q1015 NOSIG")
    assert e.visibility_sm == 6.2 and e.altimeter_hpa == 1015.0 and e.flight_category == "VFR"


def test_ceiling_is_lowest_broken_or_overcast_not_scattered():
    m = _p("KSFO 150256Z 26015KT 9SM FEW005 BKN010 OVC020 13/09 A2995")
    assert m.ceiling_ft == 1000 and m.flight_category == "MVFR"


@pytest.mark.parametrize(("vis", "ceil", "cat"), [
    (10.0, None, "VFR"), (5.0, None, "MVFR"), (None, 3000, "MVFR"), (2.9, 5000, "IFR"),
    (6.0, 900, "IFR"), (0.75, 5000, "LIFR"), (6.0, 400, "LIFR"), (None, None, None),
])
def test_flight_category_thresholds(vis, ceil, cat):
    assert flight_category(vis, ceil) == cat
