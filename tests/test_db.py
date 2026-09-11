"""Database layer. Each test runs inside a transaction that is rolled back."""

from datetime import UTC, datetime

import pytest

from preflight.db import notams as ndb
from preflight.db import weather as wdb
from preflight.decode.notam import DEMO_NOTAMS, parse_notam
from preflight.schemas import Severity
from preflight.sources.aviationweather import Metar, Taf

pytestmark = pytest.mark.db

T0 = datetime(2026, 9, 11, 2, 0, tzinfo=UTC)

# Synthetic airports so real ingested rows can never collide with these tests.
# K-prefixed so the US-domestic sample (3-letter "SFO") maps onto A as well.
A, B = "KZZY", "KZZX"


@pytest.fixture
def records():
    swapped = [r.replace("KSFO", A).replace("KJFK", B).replace("SFO", A[1:]) for r in DEMO_NOTAMS]
    return [parse_notam(r) for r in swapped]


# ---------------------------------------------------------------- notams

def test_upsert_is_idempotent(db, records):
    assert ndb.upsert_many(db, records) == 3
    assert ndb.upsert_many(db, records) == 3
    n = db.execute("SELECT count(*) FROM notams WHERE id = ANY(%s)", ([r.id for r in records],))
    assert n.fetchone()[0] == 3


def test_upsert_replaces_entities_not_duplicates(db, records):
    ndb.upsert(db, records[0])
    ndb.upsert(db, records[0])
    n = db.execute("SELECT count(*) FROM notam_entities WHERE notam_id = %s", (records[0].id,))
    assert n.fetchone()[0] == len(records[0].entities)


def test_active_at_filters_by_airport_and_window(db, records):
    ndb.upsert_many(db, records)
    here = ndb.active_at(db, A, T0)
    assert {r.id for r in here} == {"A1477/26", "!ZZY 09/142"}     # B excluded
    assert ndb.active_at(db, A, datetime(2026, 9, 12, 2, 0, tzinfo=UTC)) == []
    assert ndb.active_at(db, A, datetime(2026, 9, 10, 22, 0, tzinfo=UTC)) == []


def test_active_at_orders_by_severity(db, records):
    ndb.upsert_many(db, records)
    sev = [r.severity for r in ndb.active_at(db, A, T0)]
    assert sev == sorted(sev, key=lambda s: -s.rank)
    assert sev[0] is Severity.HIGH


def test_round_trip_preserves_record(db, records):
    ndb.upsert(db, records[0])
    back = next(r for r in ndb.active_at(db, A, T0) if r.id == records[0].id)
    assert back.model_dump() == records[0].model_dump()


def test_permanent_notam_is_always_active(db):
    rec = parse_notam(f"A0500/26 NOTAMN\nA) {A} B) 2609100000 C) PERM\nE) RWY 10L CLSD.")
    ndb.upsert(db, rec)
    assert any(r.id == "A0500/26" for r in ndb.active_at(db, A, datetime(2030, 1, 1, tzinfo=UTC)))


def test_low_confidence_queue(db):
    prose = parse_notam(
        f"A0001/26 NOTAMN\nA) {A} B) 2609100000 C) 2609110000\n"
        "E) CONTACT AIRPORT OPERATIONS PRIOR TO ARRIVAL FOR SPECIAL PROCEDURES."
    )
    good = parse_notam(DEMO_NOTAMS[0])
    ndb.upsert_many(db, [prose, good])
    queued = {r.id for r in ndb.low_confidence(db, threshold=0.6)}
    assert prose.id in queued and good.id not in queued


# ---------------------------------------------------------------- weather

def test_metar_upsert_and_latest(db):
    older = Metar(icao=A, observed_at=T0, raw="METAR OLD", flight_category="IFR")
    newer = Metar(icao=A, observed_at=datetime(2026, 9, 11, 3, 0, tzinfo=UTC),
                  raw="METAR NEW", flight_category="VFR", ceiling_ft=2500)
    assert wdb.upsert_metars(db, [older, newer]) == 2
    raw, parsed, issued = wdb.latest(db, A, "METAR")
    assert raw == "METAR NEW"
    assert parsed["flight_category"] == "VFR" and parsed["ceiling_ft"] == 2500
    assert issued == newer.observed_at


def test_metar_same_timestamp_updates_in_place(db):
    m1 = Metar(icao=B, observed_at=T0, raw="v1")
    m2 = Metar(icao=B, observed_at=T0, raw="v2")
    wdb.upsert_metars(db, [m1])
    wdb.upsert_metars(db, [m2])
    n = db.execute("SELECT count(*) FROM weather_reports WHERE icao = %s", (B,)).fetchone()[0]
    assert n == 1 and wdb.latest(db, B, "METAR")[0] == "v2"


def test_taf_validity_window_stored(db):
    t = Taf(icao=A, issued_at=T0, valid_from=T0,
            valid_to=datetime(2026, 9, 12, 6, 0, tzinfo=UTC), raw="TAF ...")
    wdb.upsert_tafs(db, [t])
    row = db.execute(
        "SELECT valid_from, valid_to FROM weather_reports WHERE icao = %s AND kind = 'TAF'", (A,)
    ).fetchone()
    assert row == (t.valid_from, t.valid_to)


def test_latest_returns_none_when_empty(db):
    assert wdb.latest(db, "ZZZZ", "METAR") is None
