from datetime import UTC, datetime

import pytest

from preflight.decode.notam import (
    NotamParseError,
    extract_entities,
    parse_notam,
    parse_notam_time,
)
from preflight.schemas import EntityState, EntityType, Phase, Severity

ICAO_SFO = """A1477/26 NOTAMN
Q) KZOA/QMRLC/IV/NBO/A/000/999/3737N12222W005
A) KSFO
B) 2609102300 C) 2609110700
E) RWY 28R CLSD DUE WIP. TWY B BTN TWY A AND TWY F CLSD.
ALTN RWY 28L AVBL. PAPI RWY 28L U/S."""

ICAO_JFK = """A0912/26 NOTAMN
Q) KZNY/QICAS/I/NBO/A/000/999/4038N07346W005
A) KJFK B) 2609110400 C) 2609111600EST
E) ILS RWY 22L U/S DUE MAINT."""

US_DOMESTIC = "!SFO 09/142 SFO TWY A BTN TWY B AND TWY C CLSD 2609102330-2609110700EST"


# ---------------------------------------------------------------- time

def test_parses_notam_timestamp_as_utc():
    assert parse_notam_time("2609102300") == datetime(2026, 9, 10, 23, 0, tzinfo=UTC)


def test_est_suffix_stripped():
    assert parse_notam_time("2609111600EST") == datetime(2026, 9, 11, 16, 0, tzinfo=UTC)


@pytest.mark.parametrize("bad", ["", "PERM", "UFN", "260910", "26091023001", "26091x2300"])
def test_unparseable_times_return_none(bad):
    assert parse_notam_time(bad) is None


def test_impossible_date_returns_none_not_exception():
    assert parse_notam_time("2613402300") is None  # month 13, day 40


# ---------------------------------------------------------------- ICAO format

def test_parses_icao_header_and_fields():
    rec = parse_notam(ICAO_SFO)
    assert rec.id == "A1477/26"
    assert rec.icao == "KSFO"
    assert rec.fir == "KZOA"
    assert rec.kind == "NEW"
    assert rec.qcode == "QMRLC"
    assert rec.traffic == "IFR/VFR"
    assert rec.scope == "aerodrome"
    assert rec.effective_from == datetime(2026, 9, 10, 23, 0, tzinfo=UTC)
    assert rec.effective_to == datetime(2026, 9, 11, 7, 0, tzinfo=UTC)
    assert not rec.estimated_end


def test_estimated_end_time_flagged():
    rec = parse_notam(ICAO_JFK)
    assert rec.estimated_end is True


def test_qcode_drives_hazard_and_severity():
    rec = parse_notam(ICAO_SFO)
    assert rec.hazard_class == "runway_closure"
    assert rec.severity is Severity.HIGH


def test_replacement_notam_records_what_it_replaces():
    rec = parse_notam("A0500/26 NOTAMR A0499/26\nA) KSFO B) 2609100000 C) PERM\nE) RWY 10L CLSD.")
    assert rec.kind == "REPLACE"
    assert rec.replaces == "A0499/26"
    assert rec.permanent is True


# ---------------------------------------------------------------- entities

def test_alternate_runway_is_not_marked_closed():
    """The regression this whole clause-scoping design exists to prevent."""
    rec = parse_notam(ICAO_SFO)
    by_ref = {e.ref: e for e in rec.entities if e.type is EntityType.RWY}
    assert by_ref["28R"].state is EntityState.CLOSED
    assert by_ref["28L"].state is EntityState.AVAILABLE
    assert by_ref["28L"].detail == "alternate"


def test_lighting_absorbs_its_runway_qualifier():
    """'PAPI RWY 28L U/S' is one lighting entity, not a lighting + a runway."""
    rec = parse_notam(ICAO_SFO)
    lighting = [e for e in rec.entities if e.type is EntityType.LIGHTING]
    assert len(lighting) == 1
    assert lighting[0].ref == "PAPI 28L"
    assert lighting[0].state is EntityState.UNSERVICEABLE
    assert not any(e.ref == "28L" and e.state is EntityState.UNSERVICEABLE
                   for e in rec.entities if e.type is EntityType.RWY)


def test_between_clause_yields_one_taxiway_with_bounds():
    rec = parse_notam(ICAO_SFO)
    twys = [e for e in rec.entities if e.type is EntityType.TWY]
    assert len(twys) == 1
    assert twys[0].ref == "B"
    assert twys[0].detail == "between A and F"


def test_cause_extracted():
    rec = parse_notam(ICAO_SFO)
    rwy_28r = next(e for e in rec.entities if e.ref == "28R")
    assert rwy_28r.cause == "WIP"


def test_navaid_recognised():
    rec = parse_notam(ICAO_JFK)
    navaids = [e for e in rec.entities if e.type is EntityType.NAVAID]
    assert len(navaids) == 1
    assert navaids[0].ref == "ILS 22L"
    assert navaids[0].state is EntityState.UNSERVICEABLE


def test_spans_point_back_into_the_body():
    rec = parse_notam(ICAO_SFO)
    for e in rec.entities:
        assert e.span is not None
        start, end = e.span
        assert rec.body[start:end]  # non-empty slice


def test_obstacle_clause():
    ents = extract_entities("CRANE ERECTED 1.2NM SE OF RWY 28L THR, 220FT AGL, UNLGTD.")
    assert any(e.type is EntityType.OBSTACLE for e in ents)


def test_airspace_restriction_defaults_to_active():
    ents = extract_entities("TFR WI 3NM RADIUS OF 3737N12222W SFC-3000FT.")
    airspace = next(e for e in ents if e.type is EntityType.AIRSPACE)
    assert airspace.state is EntityState.ACTIVE


# ---------------------------------------------------------------- US domestic

def test_parses_us_domestic_format():
    rec = parse_notam(US_DOMESTIC)
    assert rec.id == "!SFO 09/142"
    assert rec.icao == "KSFO"
    assert rec.effective_from == datetime(2026, 9, 10, 23, 30, tzinfo=UTC)
    assert rec.estimated_end is True
    assert rec.hazard_class == "taxiway"
    assert rec.severity is Severity.MEDIUM


# ---------------------------------------------------------------- phases & confidence

def test_phases_cover_ground_and_air_for_mixed_notam():
    rec = parse_notam(ICAO_SFO)
    assert Phase.TAXI in rec.phases
    assert Phase.TAKEOFF in rec.phases
    assert Phase.APPROACH in rec.phases


def test_rule_parser_never_claims_certainty():
    assert parse_notam(ICAO_SFO).decode_confidence <= 0.95


def test_low_confidence_on_unstructured_body():
    """Free-text prose is exactly what should escalate to the learned model."""
    rec = parse_notam(
        "A0001/26 NOTAMN\nA) KSFO B) 2609100000 C) 2609110000\n"
        "E) CONTACT AIRPORT OPERATIONS PRIOR TO ARRIVAL FOR SPECIAL PROCEDURES."
    )
    assert rec.decode_confidence < 0.6


# ---------------------------------------------------------------- errors & helpers

@pytest.mark.parametrize("bad", ["", "   ", "just some prose", "12345"])
def test_non_notam_input_raises(bad):
    with pytest.raises(NotamParseError):
        parse_notam(bad)


def test_active_at_respects_window():
    rec = parse_notam(ICAO_SFO)
    assert rec.active_at(datetime(2026, 9, 11, 2, 0, tzinfo=UTC))
    assert not rec.active_at(datetime(2026, 9, 10, 22, 0, tzinfo=UTC))
    assert not rec.active_at(datetime(2026, 9, 11, 8, 0, tzinfo=UTC))


def test_permanent_notam_never_expires():
    rec = parse_notam("A0500/26 NOTAMN\nA) KSFO B) 2609100000 C) PERM\nE) RWY 10L CLSD.")
    assert rec.active_at(datetime(2030, 1, 1, tzinfo=UTC))
