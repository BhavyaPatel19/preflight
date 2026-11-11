"""Does a prior report involve the hazard's mechanism?

A briefing attaches precedent so a crew can read what went wrong for others facing *this*
hazard. The retriever and the stock reranker score topical overlap, and topical overlap is not
precedent: a PAPI outage matched to a crash into runway lights, a wildlife hazard matched to a
landing flare with no animal involved. Labelling the precedent sheet put relevant precedent at
0.42 both above and below the reranker threshold (evals/precedent/HISTORY.md).

This module is the cheap, deterministic check in front of attachment: each hazard type names the
words a report about that mechanism has to contain. It does not decide relevance alone; it only
removes reports that cannot be about the hazard. A finding with no recognised mechanism is not
gated.
"""

from __future__ import annotations

import re

from preflight.schemas import Finding


def _rx(*terms: str) -> re.Pattern[str]:
    return re.compile(r"\b(?:" + "|".join(terms) + r")", re.I)


# Words a report must contain to be about the mechanism. Stems match word starts
# ("contaminat" → contaminated). Deliberately about the event, not the airport feature.
LEXICON: dict[str, re.Pattern[str]] = {
    "wildlife": _rx(
        r"birds?\b", "birdstrike", "bird strike", "wildlife", r"animals?\b", "deer", "coyote",
        r"elk\b", "moose", "geese", "goose", r"hawks?\b", "vulture", "eagle", r"gulls?\b",
        r"ducks?\b", "pelican", "turkey", "dogs?\b", "cattle", r"cows?\b", "horse", "antelope",
        r"fox\b", "rabbit", r"hogs?\b", "pig", "armadillo", "alligator", "turtle", "flock"),
    "incursion": _rx(
        "incursion", "hold short", "hold-short", "hold line", "holding position",
        "crossed the runway", "runway crossing", "crossing the runway", r"vehicles?\b",
        "tractor", "truck", "mower", "pedestrian", r"person on the runway",
        r"(?:airplane|aircraft|traffic) (?:was )?on the runway", "occupied", "line up and wait",
        "taxied onto"),
    "surface_condition": _rx(
        r"wet\b", "water", "flooded", "puddle", "snow", "slush", r"ice\b", "icy", "frost",
        "contaminat", "braking action", "rubber", r"soft\b", "rough", "pothole", "debris",
        r"FOD\b", "gravel", "uneven", "hydroplan", "mud"),
    "closure": _rx(
        "closed", "closure", "NOTAM", "construction", "work in progress", r"WIP\b",
        "runway change", "wrong runway", "barricade", r"X\b marks?", "temporar",
        "configuration", "not in use", "unavailable"),
    "taxi_route": _rx(
        "closed", "closure", "NOTAM", "construction", "wrong turn", "wrong taxiway",
        "taxi route", "reroute", "re-route", "confus", r"lost\b", "signage", r"signs?\b",
        "unfamiliar", "hold short", "hold line", "taxi clearance", "snow", r"ice\b", "icy"),
    "approach_guidance": _rx(
        r"ILS\b", "localizer", r"LOC\b", "glideslope", "glide slope", "glidepath",
        "glide path", "approach path", "vertical guidance", "non-precision", r"RNAV\b",
        r"GPS\b", "visual approach", "circling", "undershoot", "landed short",
        "short of the runway", "landing short", "out of service", "unusable", "inoperative",
        r"U/S\b", "minimums"),
    "visual_glidepath": _rx(
        r"PAPI\b", r"VASI\b", "approach light", r"ALS\b", "glidepath", "glide path",
        "approach path", "undershoot", "landed short", "short of the runway", "landing short",
        "landed long", "dark", "black hole", "runway lights", "lighting", "unlit"),
    "airport_lighting": _rx(
        r"lights?\b", "lighting", "unlit", "dark", "pilot-controlled", "pilot controlled",
        r"PCL\b", "beacon", r"PAPI\b", r"VASI\b", "illuminat"),
    "aircraft_lighting": _rx(
        "landing light", "exterior light", "position light", "navigation light", "strobe",
        "anti-collision", "beacon", "panel light", "instrument light", "cockpit light",
        "flashlight", "caution light", "lighting system", "lights? (?:failed|inoperative|out)"),
    "obstruction": _rx(
        "obstruction", "obstacle", "crane", r"towers?\b", "antenna", r"wires?\b",
        "power ?lines?", r"poles?\b", "unmarked", "marking", "marked"),
    "navaid": _rx(
        r"VOR\b", "navaid", "navigation aid", r"NDB\b", r"DME\b", "TACAN", "radial",
        r"course\b", "off course", "navigation error", "wrong fix", "out of service",
        "unusable", "inoperative", r"GPS\b"),
    "airspace": _rx(
        r"TFR\b", "temporary flight restriction", "restricted", "prohibited", "airspace",
        "intercept", "class [bcd]\b"),
    "ramp": _rx(
        "apron", "ramp", r"gates?\b", "ground collision", "wingtip", "wing tip", "marshal",
        "congest", "tug", "pushback", "closed"),
}


# An NTSB "runway/landing area condition" finding covers contamination and closed or
# unavailable runways alike.
LEXICON["runway_condition"] = re.compile(
    LEXICON["surface_condition"].pattern + "|" + LEXICON["closure"].pattern, re.I)


def mechanism(f: Finding) -> str | None:
    """The mechanism a finding's hazard implies, from its category and headline."""
    cat = (f.category or "").lower()
    h = f.headline
    if cat == "wildlife":
        return "wildlife"
    if cat == "runway":
        if re.search(r"incursion", h, re.I):
            return "incursion"
        if re.search(r"condition|surface|contaminat|snow|ice|wet", h, re.I):
            return "runway_condition"
        if re.search(r"closed|CLSD", h, re.I):
            return "closure"
        return None
    if cat == "taxiway":
        return "taxi_route"
    if cat == "approach aids":
        return "approach_guidance"
    if cat == "lighting":
        if re.search(r"PAPI|VASI|ALS\b|approach light", h):
            return "visual_glidepath"
        if re.search(r"Aircraft systems|Exterior lighting|compartment lighting|"
                     r"Lighting system", h, re.I):
            return "aircraft_lighting"
        if re.search(r"Obstruction", h, re.I):
            return "obstruction"
        return "airport_lighting"
    if cat == "navaid":
        return "navaid"
    if cat == "obstacle":
        return "obstruction"
    if cat == "airspace":
        return "airspace"
    if cat == "surface":
        return "ramp"
    return None


def involves(f: Finding, text: str) -> bool:
    """True when ``text`` mentions the finding's mechanism, or the finding has none we know.

    ``text`` should be what the briefing would show and cite: the report's title (an ASRS
    synopsis) and the matched passage."""
    m = mechanism(f)
    return True if m is None else bool(LEXICON[m].search(text))
