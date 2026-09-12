"""Delay forecasting: pure estimators and metrics; climatology and series against the DB."""

from datetime import UTC, datetime, timedelta

import pytest

from preflight.brief.core import delay_finding
from preflight.forecast.delay import (
    _quantile,
    climatology,
    local_time,
    mase,
    mean_pinball,
    pinball,
    seasonal_naive,
    series,
)
from preflight.schemas import Severity
from preflight.sources.bts import _hour, iata_to_icao

# ---------------------------------------------------------------- BTS parsing

@pytest.mark.parametrize("iata,icao", [("SFO", "KSFO"), ("jfk", "KJFK"), ("ANC", "PANC"),
                                       ("HNL", "PHNL"), ("5R2", None), ("", None)])
def test_iata_to_icao(iata, icao):
    assert iata_to_icao(iata) == icao


def test_bts_hour_parsing_including_2400():
    assert _hour("2026-05-03", "2135") == datetime(2026, 5, 3, 21)
    assert _hour("2026-05-03", '"0005"') == datetime(2026, 5, 3, 0)
    assert _hour("2026-05-03", "2400") == datetime(2026, 5, 4, 0)      # BTS midnight convention
    assert _hour("2026-05-03", "") is None and _hour("bad", "1200") is None


# ---------------------------------------------------------------- estimators

def test_seasonal_naive_repeats_last_week_then_falls_back_to_yesterday():
    ctx = [float(i % 168) for i in range(400)]
    fc = seasonal_naive(ctx, 5)
    assert fc == [float((400 + h) % 168) for h in range(5)]
    short = [None] * 30 + [7.0] * 30                        # < 168 → 24 h fallback
    assert seasonal_naive(short, 3) == [7.0, 7.0, 7.0]
    assert seasonal_naive([None, None], 2) == [0.0, 0.0]


def test_quantile_interpolates():
    assert _quantile([1.0, 2.0, 3.0, 4.0], 0.5) == 2.5
    assert _quantile([5.0], 0.9) == 5.0
    assert _quantile([], 0.5) != _quantile([], 0.5)          # NaN


# ---------------------------------------------------------------- metrics

def test_mase_is_one_for_the_seasonal_naive_itself():
    # Weekly pattern with a slow drift, so the in-sample seasonal error (the scale) is non-zero.
    ctx = [float((i % 24) + (i % 168 > 100) * 3 + i / 500) for i in range(24 * 30)]
    fc = seasonal_naive(ctx, 24)
    actual = [ctx[len(ctx) - 168 + h] for h in range(24)]    # the world repeated last week
    assert mase(actual, fc, ctx) == pytest.approx(0.0)       # perfect, so 0
    assert mase(actual, [a + 1 for a in actual], ctx) > 0
    assert mase([1.0], [1.0], [1.0] * 10) is None            # too little context to scale


def test_pinball_penalises_the_right_side():
    assert pinball(10, 8, 0.9) == pytest.approx(1.8)         # under-forecast at q90 costs 0.9×
    assert pinball(10, 12, 0.9) == pytest.approx(0.2)
    assert mean_pinball([10.0], [[8.0, 10.0, 12.0]]) == pytest.approx((0.2 + 0 + 0.2) / 3)


# ---------------------------------------------------------------- time zones

def test_local_time_for_known_and_unknown_airports():
    at = datetime(2026, 9, 12, 19, 0, tzinfo=UTC)
    assert local_time("KSFO", at) == datetime(2026, 9, 12, 12, 0)       # PDT
    assert local_time("KJFK", at) == datetime(2026, 9, 12, 15, 0)       # EDT
    assert local_time("KPHX", at) == datetime(2026, 9, 12, 12, 0)       # no DST
    assert local_time("EGLL", at) is None


# ---------------------------------------------------------------- db

@pytest.fixture
def delays(db):
    """Twelve Thursdays of 15:00 at a synthetic airport, plus a gap in the hourly series."""
    base = datetime(2026, 1, 1, 15)                                    # a Thursday
    rows = []
    for w in range(12):
        t = base + timedelta(weeks=w)
        rows.append(("KZZY", t, 40, 1, 0, 10.0 + w, 30.0 + w))
    rows.append(("KZZY", base + timedelta(hours=1), 5, 0, 0, 3.0, 5.0))  # 16:00 once
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO delay_hourly (icao, hour_local, flights, cancelled, diverted, "
            "mean_arr_delay, p90_arr_delay) VALUES (%s, %s, %s, %s, %s, %s, %s)", rows)
    return db


@pytest.mark.db
def test_series_fills_gaps(delays):
    pts = series(delays, "KZZY", hours=1000)
    assert pts[0].hour_local == datetime(2026, 1, 1, 15)
    assert pts[1].mean_arr_delay == 3.0
    assert pts[2].flights == 0 and pts[2].mean_arr_delay is None     # filled gap
    assert len(pts) == 11 * 168 + 1


@pytest.mark.db
def test_climatology_needs_four_samples_and_reports_quantiles(delays):
    c = climatology(delays, "KZZY", datetime(2026, 9, 17, 15))       # a Thursday, 15:00
    assert c is not None and c.samples == 12 and c.weekday == 3 and c.hour == 15
    assert c.p50 == pytest.approx(15.5) and c.p10 < c.p50 < c.p90
    assert climatology(delays, "KZZY", datetime(2026, 9, 17, 16)) is None   # one sample
    assert climatology(delays, "KZZY", datetime(2026, 9, 16, 15)) is None   # Wednesday


@pytest.mark.db
def test_delay_finding_uses_local_time_and_says_climatology(delays, monkeypatch):
    from preflight.forecast import delay as D

    monkeypatch.setitem(D.AIRPORT_TZ, "KZZY", "America/New_York")
    arrival_utc = datetime(2026, 9, 17, 19, 0, tzinfo=UTC)               # 15:00 EDT Thursday
    f = delay_finding(delays, "KZZY", "destination", arrival_utc)
    assert f is not None and f.category == "delay" and f.airport == "KZZY"
    assert "Thu 15:00 local" in f.headline and "median 16 min" in f.headline
    assert "Climatology, not a forecast." in f.claims[0].text
    assert f.claims[0].citations[0].kind == "forecast"
    assert f.severity is Severity.INFO
    assert delay_finding(delays, "KZZY", "departure", arrival_utc) is None
    assert delay_finding(delays, "KZZZ", "destination", arrival_utc) is None   # no tz → nothing
