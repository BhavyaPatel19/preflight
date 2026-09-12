"""ASRS source parsing. The row fixture mirrors the real export's field names."""

from datetime import date

import pytest

from preflight.schemas import Phase
from preflight.sources.asrs import AsrsReport, locale_to_icao, parse_row, phases_from

ROW = {
    "acn_num_ACN": "1002943",
    "Time_Date": "201204",
    "Place_Locale Reference": "SFO.Airport",
    "Aircraft 1.9_Flight Phase": "Climb; Takeoff / Launch",
    "Events_Anomaly": "Deviation - Track / Heading All Types",
    "Assessments.1_Primary Problem": "Human Factors",
    "Person 1.7_Human Factors": "Situational Awareness",
    "Report 1_Narrative": "Prior to takeoff we reviewed the departure. 28R would be the runway "
                          "used.",
    "Report 2_Narrative": "[Report narrative contained no additional information].",
    "Report 1.2_Synopsis": "Crew deviated from the SID out of SFO.",
}


# ---------------------------------------------------------------- locale → ICAO

@pytest.mark.parametrize("locale,expected", [
    ("SFO.Airport", "KSFO"),
    ("JFK.Airport", "KJFK"),
    ("KSFO.Airport", "KSFO"),          # already 4-letter
    ("ANC.Airport", "PANC"),           # Alaska
    ("HNL.Airport", "PHNL"),           # Hawaii
    ("ZZZ.Airport", None),             # ASRS anonymiser
    ("ZZZZ.Airport", None),
    ("ZMP.ARTCC", None),               # a centre, not an airport
    ("NCT.TRACON", None),
    ("", None), (None, None), ("garbage", None),
])
def test_locale_to_icao(locale, expected):
    assert locale_to_icao(locale) == expected


# ---------------------------------------------------------------- phases

def test_phases_map_asrs_vocabulary():
    assert phases_from("Takeoff / Launch; Initial Climb; Cruise") == (
        Phase.TAKEOFF, Phase.CLIMB, Phase.ENROUTE
    )
    assert phases_from("Final Approach; Initial Approach") == (Phase.APPROACH,)   # de-duplicated
    assert phases_from("Parked; Other All") == ()                                # unmapped dropped
    assert phases_from(None) == () and phases_from("") == ()


# ---------------------------------------------------------------- rows

def test_parse_row_builds_report():
    r = parse_row(ROW)
    assert isinstance(r, AsrsReport)
    assert r.acn == "1002943" and r.icao == "KSFO" and r.published == date(2012, 4, 1)
    assert r.phases == (Phase.CLIMB, Phase.TAKEOFF)
    assert r.primary_problem == "Human Factors"
    assert r.synopsis.startswith("Crew deviated")


def test_placeholder_second_narrative_is_dropped():
    r = parse_row(ROW)
    assert "no additional information" not in r.narrative
    assert r.narrative.startswith("Prior to takeoff")


def test_real_second_narrative_is_appended():
    r = parse_row({**ROW, "Report 2_Narrative": "First Officer's account of the same event."})
    assert r.narrative.count("\n\n") == 1 and r.narrative.endswith("same event.")


def test_text_is_narrative_then_synopsis():
    r = parse_row(ROW)
    assert r.text.startswith("Prior to takeoff") and r.text.endswith("out of SFO.")
    assert "\n\nSynopsis: " in r.text


def test_metadata_carries_taxonomy_fields():
    m = parse_row(ROW).metadata
    assert m["anomaly"].startswith("Deviation") and m["phases"] == ["climb", "takeoff"]
    assert m["locale"] == "SFO.Airport"


def test_rows_without_narrative_or_acn_are_skipped():
    assert parse_row({**ROW, "Report 1_Narrative": "", "Report 2_Narrative": ""}) is None
    assert parse_row({**ROW, "acn_num_ACN": ""}) is None


def test_bad_date_is_none_not_error():
    assert parse_row({**ROW, "Time_Date": "2012"}).published is None
    assert parse_row({**ROW, "Time_Date": "201313"}).published is None
