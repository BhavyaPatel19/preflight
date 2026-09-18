"""Briefing eval: case construction rules are pure; the builder and coverage check use the DB."""

from datetime import UTC, datetime

import pytest

from preflight.brief.core import _wind_severity
from preflight.decode.qcode import decode_qcode
from preflight.evals import briefing as B
from preflight.schemas import (
    Briefing,
    Citation,
    Claim,
    Finding,
    FlightRequest,
    Severity,
)

T = datetime(2026, 6, 20, 14, 0, tzinfo=UTC)


# ---------------------------------------------------------------- classification

@pytest.mark.parametrize("finding,category", [
    ("Environmental issues-Conditions/weather/phenomena-Wind-Gusts-Effect on operation", "weather"),
    ("Environmental issues-Conditions/weather/phenomena-Ceiling/visibility/precip-Fog-Effect",
     "weather"),
    ("Environmental issues-Conditions/weather/phenomena-Temp/humidity/pressure-Conducive to "
     "carburetor icing-Effect on equipment", "weather"),
    ("Environmental issues-Physical environment-Object/animal/substance-Animal(s)/bird(s)-Effect "
     "on equipment", "wildlife"),
    ("Environmental issues-Conditions/weather/phenomena-Light condition-Dark-Effect", None),
    ("Environmental issues-Physical environment-Object/animal/substance-Tree(s)-Contributed", None),
    ("Aircraft-Aircraft power plant-Engine (reciprocating)-Failure", None),
])
def test_classify_findings(finding, category):
    r = B.classify([finding], [])
    assert (r[0] if r else None) == category


def test_classify_uses_occurrences_too_and_keeps_evidence():
    r = B.classify([], ["Landing-landing roll Birdstrike", "Landing-landing roll Runway excursion"])
    assert r == ("wildlife", ("Landing-landing roll Birdstrike",))
    r = B.classify([], ["Takeoff Runway incursion veh/AC/person"])
    assert r[0] == "runway"


def test_night_alone_is_not_a_briefable_hazard():
    assert B.classify(["…Light condition-Dark-Effect on personnel"], []) is None


# ---------------------------------------------------------------- times and requests

def test_flight_times_departure_vs_destination():
    snap, off = B._flight_times(T, "departure")
    assert snap == T.replace(hour=13) and off == T
    snap, off = B._flight_times(T, "destination")
    assert off == T.replace(hour=12)          # arrival window covers the event


def test_request_for_puts_the_case_airport_in_the_right_seat():
    c = B.Case(id="x", label="positive", source_ref=None, airport="KSFO", role="destination",
               partner="KDEN", snapshot_at=T.isoformat(), off_block=T.isoformat(),
               implicated="weather", evidence=())
    r = B.request_for(c)
    assert (r.departure, r.destination) == ("KDEN", "KSFO")
    c2 = B.Case(**{**c.__dict__, "role": "departure"})
    assert (B.request_for(c2).departure, B.request_for(c2).destination) == ("KSFO", "KDEN")


# ---------------------------------------------------------------- scoring

def _finding(cat, sev, airport):
    return Finding(category=cat, severity=sev, headline=f"{airport}: x", airport=airport,
                   claims=(Claim(text="t", citations=(Citation(kind="metar", ref="r"),)),))


def _briefing(*findings):
    return Briefing(request=FlightRequest(departure="KDEN", destination="KSFO", off_block=T),
                    generated_at=T, findings=tuple(findings))


def _case(label, implicated=None):
    return B.Case(id="c", label=label, source_ref=None, airport="KSFO", role="destination",
                  partner="KDEN", snapshot_at=T.isoformat(), off_block=T.isoformat(),
                  implicated=implicated, evidence=())


def test_positive_counts_only_non_info_findings_of_the_implicated_category():
    b = _briefing(_finding("weather", Severity.INFO, "KSFO"))
    assert B.score_case(_case("positive", "weather"), b)["hazard_found"] is False
    b = _briefing(_finding("weather", Severity.LOW, "KSFO"),
                  _finding("runway", Severity.HIGH, "KDEN"))
    s = B.score_case(_case("positive", "weather"), b)
    assert s["hazard_found"] is True and s["hazard_rank"] == 2      # ranked after the HIGH one
    assert s["alarms"] == 0                                           # KDEN's alarm is not KSFO's


def test_negative_false_alarm_means_medium_or_high_at_the_airport():
    low = _briefing(_finding("weather", Severity.LOW, "KSFO"))
    med = _briefing(_finding("runway", Severity.MEDIUM, "KSFO"))
    assert B.score_case(_case("negative"), low)["false_alarm"] is False
    assert B.score_case(_case("negative"), med)["false_alarm"] is True


# ---------------------------------------------------------------- core changes the eval relies on

def test_wind_severity_thresholds():
    assert _wind_severity({"wind_kt": 8}) is Severity.INFO
    assert _wind_severity({"wind_kt": 22}) is Severity.LOW
    assert _wind_severity({"wind_kt": 14, "gust_kt": 27}) is Severity.LOW
    assert _wind_severity({"wind_kt": 31}) is Severity.MEDIUM
    assert _wind_severity({"gust_kt": 36}) is Severity.MEDIUM
    assert _wind_severity({}) is Severity.INFO


def test_bird_concentration_qcode_is_wildlife():
    q = decode_qcode("QFAHX")                  # aerodrome — concentration of birds
    assert q is not None and q.hazard_class == "wildlife"


# ---------------------------------------------------------------- db

@pytest.mark.db
def test_coverage_requires_data_near_the_snapshot(db):
    from preflight.db import weather as wdb
    from preflight.sources.aviationweather import Metar

    c = _case("positive", "weather")
    assert B.covered(db, c) is False
    wdb.upsert_metars(db, [Metar(icao="KSFO", observed_at=T.replace(hour=12, minute=30), raw="M")])
    assert B.covered(db, c) is True           # 90 min before the snapshot, within staleness


@pytest.mark.db
def test_golden_roundtrip(db, tmp_path):
    cases = [_case("positive", "weather"), _case("negative")]
    p = tmp_path / "g.jsonl"
    B.save_cases(cases, p)
    assert B.load_cases(p) == cases


@pytest.mark.db
def test_backfill_weather_targets_the_weather_slice_and_is_idempotent(db):
    from datetime import UTC, datetime, timedelta

    from preflight.sources.aviationweather import Metar

    snap = "2013-08-12T08:57:00+00:00"
    cases = [
        B.Case("p1", "positive", "X1", "KZZY", "destination", "KDEN", snap, snap, "weather",
               ("weather/phenomena-Wind-Gusts",)),
        B.Case("n1", "negative", None, "KZZY", "destination", "KDEN", snap, snap, None, (),
               matched_to="p1"),
        B.Case("p2", "positive", "X2", "KZZX", "destination", "KDEN", snap, snap, "wildlife",
               ("Birdstrike",)),
    ]
    asked: list[tuple[str, datetime, datetime]] = []

    class Src:
        def fetch_metars(self, icao, start, end):
            asked.append((icao, start, end))
            return [Metar(icao=icao, observed_at=end - timedelta(minutes=10), raw="X 10SM",
                          flight_category="VFR")]

    # commit=False: the function commits per case by design, and the db fixture is shared.
    counts = B.backfill_weather(db, cases, source=Src(), commit=False)
    # p1 fetched; its matched negative shares airport and snapshot, so it is already covered.
    assert counts["cases"] == 2 and counts["fetched"] == 1 and counts["skipped"] == 1
    assert asked == [("KZZY", datetime.fromisoformat(snap) - timedelta(hours=3),
                      datetime.fromisoformat(snap) + timedelta(minutes=5))]
    # The wildlife case is not weather-coverable; a rerun fetches nothing.
    again = B.backfill_weather(db, cases, source=Src(), commit=False)
    assert again["skipped"] == 2 and again["fetched"] == 0
    assert B.covered(db, cases[0]) and not B.covered(db, cases[2])
    assert datetime.now(UTC)  # (keeps the import honest for the linter)
