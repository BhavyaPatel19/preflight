"""Mechanism gate: which hazard implies which words, and the words it requires."""

from preflight.brief.mechanism import involves, mechanism
from preflight.schemas import Citation, Claim, Finding, Severity

_C = (Claim(text="x", citations=(Citation(kind="ntsb", ref="x"),)),)


def _f(category: str, headline: str) -> Finding:
    return Finding(category=category, severity=Severity.HIGH, headline=headline, claims=_C)


def test_mechanism_from_category_and_headline() -> None:
    assert mechanism(_f("wildlife", "KEEN: wildlife — Animal(s)/bird(s)")) == "wildlife"
    assert mechanism(_f("runway", "KCCB: runway — Landing Runway incursion veh/AC")) == "incursion"
    assert mechanism(_f("runway", "KSGS: runway — Runway/landing area condition")) \
        == "runway_condition"
    assert mechanism(_f("runway", "KLAX: Runway 25L closed (work in progress)")) == "closure"
    assert mechanism(_f("lighting", "KSLC: PAPI 34L unserviceable")) == "visual_glidepath"
    assert mechanism(_f("lighting", "KMTH: lighting — Aircraft-Aircraft systems-Lighting system"
                         "-Exterior lighting-Malfunction")) == "aircraft_lighting"
    assert mechanism(_f("lighting", "KIAD: HIRL 01C unserviceable")) == "airport_lighting"
    assert mechanism(_f("forecast", "KSFO: delays")) is None


def test_involves_requires_the_mechanism_words() -> None:
    wild = _f("wildlife", "KEEN: wildlife — Landing-flare/touchdown Wildlife encounter")
    assert involves(wild, "the airplane struck a deer during the landing roll")
    assert not involves(wild, "improper landing flare in gusty wind, bounced landing")
    closed = _f("runway", "KPHX: Runway 08 closed")
    assert involves(closed, "landed on a closed runway after not reviewing the NOTAM")
    assert not involves(closed, "failure to maintain directional control during takeoff")


def test_unknown_mechanism_is_not_gated() -> None:
    assert involves(_f("forecast", "KSFO: delays"), "anything at all")
