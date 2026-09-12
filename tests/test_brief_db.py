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
