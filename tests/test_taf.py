"""TAF decoding and the forecast hazards a briefing draws from it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from preflight.brief.core import forecast_hazards, weather_findings
from preflight.db.weather import WeatherRow
from preflight.decode.taf import TafParseError, parse_taf
from preflight.schemas import Severity

ISSUED = datetime(2026, 9, 10, 17, 30, tzinfo=UTC)
RAW = """TAF KJFK 101730Z 1018/1124 27012G22KT P6SM SCT050
 FM110200 30025G38KT 3SM -SHRA BKN008
 TEMPO 1104/1108 1SM TSRA OVC005CB
 PROB30 1110/1114 VRB05KT 1/2SM FG
 BECMG 1114/1116 32010KT
 FM111800 VRB03KT P6SM SKC="""


def _at(day: int, hour: int) -> datetime:
    return datetime(2026, 9, day, tzinfo=UTC) + timedelta(hours=hour)


def _row(raw: str = RAW) -> WeatherRow:
    return WeatherRow(raw=raw, parsed={}, issued_at=ISSUED, valid_from=_at(10, 18),
                      valid_to=_at(11, 24))


# ---------------------------------------------------------------- decoding

def test_periods_follow_the_change_groups() -> None:
    ps = {(p.kind, p.start): p for p in parse_taf(RAW, issued_at=ISSUED)}
    base = ps[("BASE", _at(10, 18))]
    assert base.end == _at(11, 2) and (base.wind_kt, base.gust_kt) == (12, 22)
    fm = ps[("FM", _at(11, 2))]
    assert fm.end == _at(11, 14)                          # cut by the BECMG that follows
    assert (fm.gust_kt, fm.visibility_sm, fm.ceiling_ft, fm.flight_category) == (38, 3, 800, "IFR")


def test_becmg_changes_only_what_it_lists() -> None:
    becmg = next(p for p in parse_taf(RAW, issued_at=ISSUED) if p.kind == "BECMG")
    assert (becmg.wind_kt, becmg.gust_kt) == (10, None)    # wind changed
    assert (becmg.visibility_sm, becmg.ceiling_ft) == (3, 800)   # the rest carried over
    assert becmg.text == "BECMG 1114/1116 32010KT"


def test_tempo_and_prob_stay_temporary_and_hour_24_rolls_over() -> None:
    ps = parse_taf(RAW, issued_at=ISSUED)
    tempo = next(p for p in ps if p.kind == "TEMPO")
    prob = next(p for p in ps if p.kind == "PROB")
    assert tempo.temporary and tempo.wx == ("TSRA",) and tempo.ceiling_ft == 500
    assert prob.probability == 30 and prob.flight_category == "LIFR"
    assert max(p.end for p in ps) == _at(12, 0)            # "1124" is midnight of the 12th


def test_month_boundary_resolves_forward() -> None:
    issued = datetime(2026, 8, 31, 23, 40, tzinfo=UTC)
    ps = parse_taf("TAF KSFO 312340Z 0100/0206 28010KT P6SM SKC", issued_at=issued)
    assert ps[0].start == datetime(2026, 9, 1, tzinfo=UTC)


def test_validity_falls_back_to_the_feed() -> None:
    ps = parse_taf("TAF KSFO 101730Z 28010KT P6SM SKC", issued_at=ISSUED,
                   valid_from=_at(10, 18), valid_to=_at(11, 24))
    assert (ps[0].start, ps[0].end) == (_at(10, 18), _at(12, 0))


@pytest.mark.parametrize("raw", ["TAF ...", "METAR KSFO 110256Z 28010KT", "TAF KSFO 101730Z"])
def test_malformed_tafs_raise(raw: str) -> None:
    with pytest.raises(TafParseError):
        parse_taf(raw, issued_at=ISSUED)


# ---------------------------------------------------------------- briefing

def test_hazards_in_the_window_are_cited_worst_first() -> None:
    f, gap = forecast_hazards("KJFK", "destination", _row(),
                              window_start=_at(11, 3), window_end=_at(11, 9))
    assert gap is None and f is not None
    assert f.category == "weather" and f.severity is Severity.MEDIUM   # IFR + TS, gusts 38
    cites = [c.citations[0] for c in f.claims]
    assert all(c.kind == "taf" and c.ref == "KJFK@101730Z" for c in cites)
    assert cites[0].quote is not None and cites[0].quote.startswith("FM110200 30025G38KT")
    assert any("TEMPO 1104/1108" in (c.quote or "") for c in cites)


def test_prob_is_briefed_one_step_lower() -> None:
    f, _ = forecast_hazards("KJFK", "destination", _row(),
                            window_start=_at(11, 10, ), window_end=_at(11, 11))
    assert f is not None
    prob = next(c for c in f.claims if "chance of 30 %" in c.text)
    assert "LIFR" in prob.text
    # The window also holds the IFR FM period (MEDIUM); the PROB30 LIFR (HIGH) drops to MEDIUM.
    assert f.severity is Severity.MEDIUM


def test_a_quiet_window_says_nothing() -> None:
    f, gap = forecast_hazards("KJFK", "destination", _row(),
                              window_start=_at(11, 19), window_end=_at(11, 22))
    assert f is None and gap is None


def test_unreadable_taf_is_an_abstention_not_silence() -> None:
    f, gap = forecast_hazards("KJFK", "destination", _row("TAF garbled"),
                              window_start=_at(11, 3), window_end=_at(11, 9))
    assert f is None and gap is not None and gap.reason == "parse_failure"


def test_departures_now_get_forecast_hazards() -> None:
    now = _at(11, 2)
    fs, gaps = weather_findings("KJFK", "departure", None, _row(), now=now,
                                window_start=_at(11, 3), window_end=_at(11, 5))
    assert any(f.category == "weather" and f.claims[0].citations[0].kind == "taf" for f in fs)
    # No METAR is still a gap; the forecast does not stand in for an observation.
    assert any(g.topic == "KJFK current weather" for g in gaps)
