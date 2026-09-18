"""End-to-end briefing against the real database, synthetic airports, rolled back."""

from datetime import UTC, datetime, timedelta

import pytest

from preflight.brief import build_briefing
from preflight.db import notams as ndb
from preflight.db import weather as wdb
from preflight.decode.notam import DEMO_NOTAMS, parse_notam
from preflight.schemas import FlightRequest, Severity
from preflight.sources.aviationweather import Metar, Taf

pytestmark = pytest.mark.db

A, B = "KZZY", "KZZX"
T0 = datetime(2026, 9, 11, 2, 30, tzinfo=UTC)


def test_briefing_end_to_end(db):
    recs = [parse_notam(r.replace("KSFO", A).replace("KJFK", B).replace("SFO", A[1:]))
            for r in DEMO_NOTAMS]
    ndb.upsert_many(db, recs)
    wdb.upsert_metars(db, [
        Metar(icao=A, observed_at=T0 - timedelta(minutes=10), raw="METAR A", flight_category="VFR"),
        Metar(icao=B, observed_at=T0 - timedelta(hours=5), raw="METAR B", flight_category="IFR"),
    ])
    wdb.upsert_tafs(db, [Taf(icao=B, issued_at=T0, valid_from=T0,
                             valid_to=T0 + timedelta(hours=24), raw="TAF B")])

    b = build_briefing(db, FlightRequest(departure=A, destination=B, off_block=T0), now=T0)

    ranked = b.ranked()
    assert ranked[0].severity is Severity.HIGH                # runway closure leads
    assert ranked[0].headline.startswith(f"{A}: Runway 28R closed")
    assert any(f.category == "approach aids" and B in f.headline for f in ranked)   # ILS at B
    assert any(f.category == "forecast" and B in f.headline for f in ranked)        # TAF covers
    assert b.grounded                                          # nothing verified False
    assert b.sources_considered >= 3 + 2 + 1

    # B's METAR is 5h old: abstain, do not cite.
    assert not any(f.category == "weather" and B in f.headline for f in ranked)
    reasons = {(a.topic, a.reason) for a in b.abstentions}
    assert (f"{B} current weather", "stale_source") in reasons

    # Every claim in the briefing carries a citation with a quote — the grounding contract.
    for f in b.findings:
        for c in f.claims:
            assert c.citations and all(cit.quote for cit in c.citations)


def _reasons(b):
    return {(a.topic, a.reason) for a in b.abstentions}


def test_airport_never_archived_is_a_coverage_gap_not_silence(db):
    """No NOTAMs on record at all → abstain; NOTAMs on record but none in force → nothing."""
    from datetime import UTC as _UTC

    from preflight.db import runs as rdb

    rdb.record_run(db, kind="notams", source="file:test", started_at=datetime.now(_UTC),
                   finished_at=datetime.now(_UTC), status="ok", counts={"unparseable": 0})
    b = build_briefing(db, FlightRequest(departure=A, destination=B, off_block=T0), now=T0)
    assert (f"{A} NOTAMs", "no_coverage") in _reasons(b)

    old = parse_notam(DEMO_NOTAMS[0].replace("KSFO", A)).model_copy(
        update={"effective_from": T0 - timedelta(days=9), "effective_to": T0 - timedelta(days=8)})
    ndb.upsert(db, old)
    b = build_briefing(db, FlightRequest(departure=A, destination=B, off_block=T0), now=T0)
    assert (f"{A} NOTAMs", "no_coverage") not in _reasons(b)
    assert not any(f.category != "delay" and A in f.headline for f in b.findings)


def test_destination_without_delay_history_abstains_departure_does_not(db):
    b = build_briefing(db, FlightRequest(departure=A, destination=B, off_block=T0), now=T0)
    assert (f"{B} arrival delay", "no_coverage") in _reasons(b)
    assert (f"{A} arrival delay", "no_coverage") not in _reasons(b)


def test_rejected_notams_in_the_latest_fetch_are_declared(db):
    from datetime import UTC as _UTC

    from preflight.db import runs as rdb

    now = datetime.now(_UTC) + timedelta(minutes=1)
    rdb.record_run(db, kind="notams", source="file:test", started_at=now, finished_at=now,
                   status="ok", counts={"fetched": 5, "stored": 3, "unparseable": 2})
    b = build_briefing(db, FlightRequest(departure=A, destination=B, off_block=T0), now=T0)
    gap = next(a for a in b.abstentions if a.reason == "parse_failure")
    assert gap.topic == "NOTAM decoding" and gap.detail.startswith("2 NOTAMs in the latest fetch")


def test_latest_weather_respects_as_of(db):
    """A time-travel briefing must not see a report issued after its snapshot."""
    from preflight.sources.aviationweather import Metar

    wdb.upsert_metars(db, [
        Metar(icao=A, observed_at=T0 - timedelta(hours=3), raw="OLD", flight_category="IFR"),
        Metar(icao=A, observed_at=T0 + timedelta(hours=2), raw="NEW", flight_category="VFR"),
    ])
    assert wdb.latest(db, A, "METAR").raw == "NEW"
    assert wdb.latest(db, A, "METAR", as_of=T0).raw == "OLD"
    assert wdb.latest(db, A, "METAR", as_of=T0 - timedelta(hours=4)) is None
    b = build_briefing(db, FlightRequest(departure=A, destination=B, off_block=T0), now=T0)
    wx = [f for f in b.findings if f.category == "weather" and A in f.headline]
    assert not wx and (f"{A} current weather", "stale_source") in _reasons(b)   # OLD is 3 h old
