"""NTSB source parsing. Fixture rows mirror mdb-export's CSV column names and formats."""

from datetime import date

import pytest

from preflight.schemas import Phase
from preflight.sources.ntsb import (
    apt_to_icao,
    build_event,
    parse_mdb_date,
    phase_from_occurrence,
)

EVENT = {
    "ev_id": "20080118X00073", "ntsb_no": "SEA08LA061", "ev_type": "ACC",
    "ev_date": "01/14/08 0", "ev_time": "329", "ev_tmzn": "UTC",
    "ev_city": "San Francisco", "ev_state": "CA", "ev_nr_apt_id": "SFO",
    "apt_name": "San Francisco Intl", "dec_latitude": "37.618", "dec_longitude": "-122.375",
    "light_cond": "NITE", "wx_cond_basic": "VMC", "vis_sm": "10.0",
    "wind_dir_deg": "300", "wind_vel_kts": "7", "sky_cond_ceil": "", "ev_highest_injury": "NONE",
}
NARR = {
    "ev_id": "20080118X00073", "Aircraft_Key": "1",
    "narr_accp": "On January 13, 2008, a Boeing 757 was being towed and collided with a CL-600.",
    "narr_accf": "The tug driver did not see the parked airplane.",
    "narr_cause": "The tow crew's inadequate visual lookout.\r\n\r\n", "narr_inc": "",
}
FINDINGS = [
    {"ev_id": "20080118X00073", "finding_code": "01062012", "finding_description":
     "Personnel issues-Action/decision-Info processing/decision-Ground crew", "Cause_Factor": "C",
     "cm_inPc": "1"},
    {"ev_id": "20080118X00073", "finding_code": "03062040", "finding_description":
     "Environmental issues-Physical environment-Object/animal/substance", "Cause_Factor": "",
     "cm_inPc": "0"},
]
SEQ = [
    {"ev_id": "20080118X00073", "Occurrence_No": "2",
     "Occurrence_Description": "Pushback/towing Ground collision"},
    {"ev_id": "20080118X00073", "Occurrence_No": "1",
     "Occurrence_Description": "Landing-landing roll Runway excursion"},
]


@pytest.mark.parametrize("ident,expected", [
    ("SFO", "KSFO"), ("sfo", "KSFO"), ("KSFO", "KSFO"), ("ANC", "PANC"), ("HNL", "PHNL"),
    ("5R2", None),                 # small field, no ICAO code
    ("PVT", None), ("NONE", None), ("N/A", None), ("", None), (None, None),
])
def test_apt_to_icao(ident, expected):
    assert apt_to_icao(ident) == expected


@pytest.mark.parametrize("desc,expected", [
    ("Landing-landing roll Runway excursion", Phase.LANDING),
    ("Enroute-cruise Loss of engine power", Phase.ENROUTE),
    ("Approach-VFR pattern final Loss of control", Phase.APPROACH),
    ("Takeoff-rejected takeoff Runway excursion", Phase.TAKEOFF),
    ("Initial climb Loss of control in flight", Phase.CLIMB),
    ("Emergency descent Off-field landing", Phase.DESCENT),
    ("Pushback/towing Ground collision", Phase.TAXI),
    ("Maneuvering-low-alt flying Collision", None),
    ("Prior to flight Preflight or dispatch", None),
    ("Post-impact Fire", None), ("", None), (None, None),
])
def test_phase_from_occurrence(desc, expected):
    assert phase_from_occurrence(desc) == expected


def test_parse_mdb_date_formats():
    assert parse_mdb_date("01/14/08 0") == date(2008, 1, 14)
    assert parse_mdb_date("09/25/20 18:05:31") == date(2020, 9, 25)
    assert parse_mdb_date("12/31/2025") == date(2025, 12, 31)
    assert parse_mdb_date("") is None and parse_mdb_date("garbage") is None


def test_build_event_assembles_all_tables():
    e = build_event(EVENT, NARR, FINDINGS, SEQ)
    assert e.ev_id == "20080118X00073" and e.ntsb_no == "SEA08LA061" and e.kind == "ACC"
    assert e.date == date(2008, 1, 14) and e.local_time == "0329" and e.tz == "UTC"
    assert e.icao == "KSFO" and e.light == "NITE" and e.wx_basic == "VMC"
    assert e.visibility_sm == 10.0 and e.wind_dir == 300 and e.ceiling_ft is None
    assert e.lat == pytest.approx(37.618)


def test_findings_keep_cause_flag_and_pc_membership():
    e = build_event(EVENT, NARR, FINDINGS, SEQ)
    assert [f.cause_factor for f in e.findings] == ["C", None]
    assert [f.in_probable_cause for f in e.findings] == [True, False]


def test_phases_from_sequence_in_order_and_deduplicated():
    e = build_event(EVENT, NARR, FINDINGS, SEQ)
    # build_event takes the sequence as given; ordering by Occurrence_No is iter_events' job.
    assert e.phases == (Phase.TAXI, Phase.LANDING)
    assert e.occurrences[0].startswith("Pushback")


def test_text_layers_narrative_cause_findings_sequence():
    t = build_event(EVENT, NARR, FINDINGS, SEQ).text
    assert t.startswith("On January 13, 2008")
    assert "\n\nProbable cause: The tow crew's inadequate visual lookout." in t
    assert "\n\nFindings: Personnel issues" in t and "\n\nSequence: Pushback" in t
    assert "\r" not in t.split("Findings:")[0]     # CRLF from the cause field stripped


def test_missing_narrative_pieces_are_tolerated():
    e = build_event(EVENT, {"narr_cause": "Cause only."}, [], [])
    assert e.text == "Probable cause: Cause only." and e.phases == () and e.findings == ()


def test_title_and_metadata():
    e = build_event(EVENT, NARR, FINDINGS, SEQ)
    assert e.title == "SEA08LA061 — San Francisco, CA — 2008-01-14"
    m = e.metadata
    assert m["highest_injury"] == "NONE" and m["phases"] == ["taxi", "landing"]
    assert m["findings"][0]["in_probable_cause"] is True
