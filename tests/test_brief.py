"""Deterministic briefing core. Pure tests here; the end-to-end test is in test_brief_db.py."""

from datetime import UTC, datetime, timedelta

from preflight.brief.core import headline, notam_findings, weather_findings, windows
from preflight.brief.render import render_text
from preflight.db.weather import WeatherRow
from preflight.decode.notam import DEMO_NOTAMS, parse_notam
from preflight.schemas import Briefing, FlightRequest, Phase, Severity

T0 = datetime(2026, 9, 11, 2, 30, tzinfo=UTC)
REQ = FlightRequest(departure="KSFO", destination="KJFK", alternates=("KBOS",), off_block=T0)


def _metar(cat, issued, **parsed):
    return WeatherRow(raw=f"METAR {cat}", parsed={"flight_category": cat, **parsed},
                      issued_at=issued, valid_from=None, valid_to=None)


def _taf(issued, start, end):
    return WeatherRow(raw="TAF ...", parsed={}, issued_at=issued, valid_from=start, valid_to=end)


# ---------------------------------------------------------------- windows

def test_windows_cover_every_airport_with_a_role():
    w = windows(REQ)
    assert [(icao, role) for icao, role, *_ in w] == [
        ("KSFO", "departure"), ("KJFK", "destination"), ("KBOS", "alternate")
    ]
    dep = next(x for x in w if x[1] == "departure")
    assert dep[2] < T0 < dep[3]
    dest = next(x for x in w if x[1] == "destination")
    assert dest[2] > T0 and dest[3] - dest[2] > timedelta(hours=6)


def test_naive_off_block_is_treated_as_utc():
    naive = FlightRequest(departure="KSFO", destination="KJFK", off_block=T0.replace(tzinfo=None))
    assert windows(naive)[0][2].tzinfo is UTC


# ---------------------------------------------------------------- headlines

def test_headline_from_entities_not_raw_text():
    rec = parse_notam(DEMO_NOTAMS[0])
    h = headline(rec)
    assert h.startswith("Runway 28R closed")
    assert "work in progress" in h            # cause expanded, not "WIP"
    assert "until 11 Sep 0700Z" in h
    assert "CLSD" not in h                    # never leaks contractions


def test_headline_prefers_the_degraded_entity():
    rec = parse_notam("A0001/26 NOTAMN\nA) KSFO B) 2609100000 C) 2609110000\n"
                      "E) ALTN RWY 28L AVBL. PAPI RWY 28L U/S.")
    assert headline(rec).startswith("PAPI 28L unserviceable")


def test_headline_marks_permanent_and_estimated():
    perm = parse_notam("A0002/26 NOTAMN\nA) KSFO B) 2609100000 C) PERM\nE) TWY Z CLSD.")
    est = parse_notam("A0003/26 NOTAMN\nA) KSFO B) 2609100000 C) 2609110000EST\nE) TWY Z CLSD.")
    assert headline(perm).endswith(", permanent")
    assert headline(est).endswith("(est)")


# ---------------------------------------------------------------- NOTAM findings

def test_high_and_medium_become_individual_cited_findings():
    recs = [parse_notam(DEMO_NOTAMS[0]), parse_notam(DEMO_NOTAMS[2])]  # HIGH runway, MED taxiway
    fs = notam_findings("KSFO", "departure", recs)
    assert [f.severity for f in fs] == [Severity.HIGH, Severity.MEDIUM]
    assert fs[0].category == "runway" and fs[0].headline.startswith("KSFO: Runway 28R closed")
    assert fs[0].claims[0].citations[0].kind == "notam"
    assert fs[0].claims[0].citations[0].ref == "A1477/26"
    assert fs[0].claims[0].citations[0].quote.startswith("RWY 28R CLSD")


def test_phases_filtered_to_the_airport_role():
    rec = parse_notam(DEMO_NOTAMS[0])                     # taxi/takeoff/landing/approach
    dep = notam_findings("KSFO", "departure", [rec])[0]
    dest = notam_findings("KSFO", "destination", [rec])[0]
    assert set(dep.phases) <= {Phase.TAXI, Phase.TAKEOFF, Phase.CLIMB}
    assert set(dest.phases) <= {Phase.DESCENT, Phase.APPROACH, Phase.LANDING}


def test_minor_notams_collapsed_but_every_one_cited():
    minor = [parse_notam(f"A{i:04d}/26 NOTAMN\nQ) KZOA/QFAXX/IV/M/A/000/999/\nA) KSFO "
                         f"B) 2609100000 C) 2609120000\nE) AD MISC ITEM {i}.") for i in range(8)]
    assert all(r.severity in {Severity.INFO, Severity.LOW} for r in minor)
    fs = notam_findings("KSFO", "departure", minor)
    assert len(fs) == 1 and fs[0].severity is Severity.INFO
    assert "8 further NOTAMs" in fs[0].headline
    assert {c.ref for c in fs[0].claims[0].citations} == {r.id for r in minor}


def test_no_records_no_findings():
    assert notam_findings("KSFO", "departure", []) == []


# ---------------------------------------------------------------- weather findings

def test_lifr_is_high_and_cites_the_metar():
    now = T0
    fs, gaps = weather_findings(
        "KJFK", "destination", _metar("LIFR", now - timedelta(minutes=20), ceiling_ft=200,
                                       visibility_sm=0.5),
        _taf(now, now, now + timedelta(hours=24)), now=now,
        window_start=now + timedelta(hours=1), window_end=now + timedelta(hours=8),
    )
    wx = next(f for f in fs if f.category == "weather")
    assert wx.severity is Severity.HIGH
    assert "ceiling 200 ft" in wx.headline and "vis 0.5 SM" in wx.headline
    assert wx.claims[0].citations[0].kind == "metar"
    assert wx.claims[0].citations[0].quote == "METAR LIFR"
    assert gaps == []


def test_calm_wind_renders_as_calm():
    now = T0
    fs, _ = weather_findings("KSFO", "departure",
                             _metar("VFR", now, wind_dir=0, wind_kt=0), None,
                             now=now, window_start=now, window_end=now)
    assert "wind calm" in fs[0].headline


def test_stale_metar_abstains_rather_than_cites():
    now = T0
    fs, gaps = weather_findings("KSFO", "departure",
                                _metar("VFR", now - timedelta(hours=3)), None,
                                now=now, window_start=now, window_end=now)
    assert fs == []
    assert len(gaps) == 1 and gaps[0].reason == "stale_source" and "180 min" in gaps[0].detail


def test_missing_metar_abstains_no_coverage():
    _, gaps = weather_findings("KSFO", "departure", None, None,
                               now=T0, window_start=T0, window_end=T0)
    assert gaps[0].reason == "no_coverage" and "KSFO" in gaps[0].topic


def test_taf_outside_window_is_a_gap_for_destination_only():
    now = T0
    old_taf = _taf(now - timedelta(days=1), now - timedelta(days=1), now - timedelta(hours=12))
    metar = _metar("VFR", now)
    _, dest_gaps = weather_findings("KJFK", "destination", metar, old_taf, now=now,
                                    window_start=now + timedelta(hours=1),
                                    window_end=now + timedelta(hours=8))
    _, dep_gaps = weather_findings("KSFO", "departure", metar, old_taf, now=now,
                                   window_start=now, window_end=now + timedelta(hours=1))
    assert [g.reason for g in dest_gaps] == ["no_coverage"] and "forecast" in dest_gaps[0].topic
    assert dep_gaps == []


# ---------------------------------------------------------------- render

def test_render_text_lists_findings_then_abstentions():
    rec = parse_notam(DEMO_NOTAMS[0])
    b = Briefing(request=REQ, generated_at=T0,
                 findings=tuple(notam_findings("KSFO", "departure", [rec])),
                 abstentions=tuple(weather_findings("KSFO", "departure", None, None, now=T0,
                                                    window_start=T0, window_end=T0)[1]),
                 sources_considered=1, latency_ms=3)
    out = render_text(b)
    assert "KSFO → KJFK (alt KBOS)" in out
    assert "[HIGH] RUNWAY" in out and "[notam:A1477/26]" in out
    assert "NOT DETERMINED" in out and "[no_coverage]" in out
    assert out.index("[HIGH]") < out.index("NOT DETERMINED")
