"""FAA / ICAO contraction dictionary.

NOTAM bodies are written in a telegraphic dialect: ``RWY 28R CLSD DUE WIP``.
Expanding it is a lookup, not a language-modelling problem, so it happens here
in the deterministic layer. Everything the rules can resolve is work the
learned extractor and the LLM never have to pay for.

Source: FAA Order JO 7340.2 (Contractions) and ICAO Doc 8400 (PANS-ABC).
"""

from __future__ import annotations

import re

CONTRACTIONS: dict[str, str] = {
    # A
    "ABN": "aerodrome beacon", "ABV": "above", "ACFT": "aircraft", "ACT": "active",
    "ADJ": "adjacent", "ADZ": "advise", "AFT": "after", "AGL": "above ground level",
    "ALS": "approach light system", "ALT": "altitude", "ALTM": "altimeter",
    "ALTN": "alternate", "AMDT": "amendment", "AP": "airport", "APCH": "approach",
    "APN": "apron", "APP": "approach control", "ARFF": "aircraft rescue and fire fighting",
    "ARP": "airport reference point", "ARR": "arrival",
    "ASDA": "accelerate-stop distance available",
    "ASPH": "asphalt", "ATC": "air traffic control", "AUTH": "authorized", "AVBL": "available",
    "AWOS": "automated weather observing system", "AZM": "azimuth",
    # B
    "BA": "braking action", "BCN": "beacon", "BLW": "below", "BTN": "between", "BYD": "beyond",
    # C
    "CAT": "category", "CHG": "change", "CIG": "ceiling", "CL": "centerline", "CLSD": "closed",
    "CMSND": "commissioned", "CNL": "cancel", "COM": "communications", "CONC": "concrete",
    "COND": "condition", "CONS": "continuous", "CONST": "construction", "CTC": "contact",
    "CTL": "control",
    # D
    "DCMSND": "decommissioned", "DCT": "direct", "DEP": "departure", "DEST": "destination",
    "DH": "decision height", "DISP": "displaced", "DIST": "distance", "DLA": "delay",
    "DLY": "daily", "DME": "distance measuring equipment", "DP": "departure procedure",
    # E
    "EB": "eastbound", "EFF": "effective", "ELEV": "elevation", "ENG": "engine",
    "ENRT": "en route", "EXC": "except",
    # F
    "FAF": "final approach fix", "FDC": "flight data center", "FL": "flight level",
    "FPM": "feet per minute", "FREQ": "frequency", "FRH": "fly runway heading",
    "FRI": "Friday", "FSS": "flight service station", "FT": "feet",
    # G
    "GC": "ground control", "GCA": "ground controlled approach", "GP": "glide path",
    "GPS": "global positioning system", "GRVL": "gravel", "GS": "glide slope",
    # H
    "HAA": "height above airport", "HAT": "height above touchdown", "HEL": "helicopter",
    "HELI": "heliport", "HIRL": "high intensity runway lights", "HLDG": "holding",
    "HOL": "holiday", "HR": "hour",
    # I
    "IAF": "initial approach fix", "IAP": "instrument approach procedure",
    "IF": "intermediate fix", "IFR": "instrument flight rules",
    "ILS": "instrument landing system", "IM": "inner marker",
    "IMC": "instrument meteorological conditions", "INBD": "inbound",
    "INDEFLY": "indefinitely", "INFO": "information", "INOP": "inoperative",
    "INT": "intersection", "INTL": "international", "INTST": "intensity",
    # L
    "LAT": "latitude", "LC": "local control", "LCTD": "located",
    "LDA": "localizer type directional aid", "LDG": "landing", "LGT": "light",
    "LGTD": "lighted", "LIRL": "low intensity runway lights",
    "LLWAS": "low level wind shear alert system", "LLZ": "localizer", "LOC": "localizer",
    "LOM": "compass locator at outer marker", "LONG": "longitude",
    "LSR": "loose snow on runway",
    # M
    "MAINT": "maintenance", "MALS": "medium intensity approach lighting system",
    "MALSF": "medium intensity approach lighting system with sequenced flashers",
    "MALSR": "medium intensity approach lighting system with runway alignment indicator lights",
    "MAPT": "missed approach point", "MCA": "minimum crossing altitude",
    "MDA": "minimum descent altitude", "MEA": "minimum en route altitude", "MED": "medium",
    "MIN": "minute", "MIRL": "medium intensity runway lights",
    "MLS": "microwave landing system", "MM": "middle marker", "MNM": "minimum",
    "MNT": "monitor", "MOA": "military operations area", "MON": "Monday",
    "MSA": "minimum safe altitude", "MSG": "message", "MSL": "mean sea level",
    "MU": "friction coefficient", "MUNI": "municipal",
    # N
    "NA": "not authorized", "NAV": "navigation", "NB": "northbound",
    "NDB": "nondirectional radio beacon", "NE": "northeast", "NGT": "night",
    "NM": "nautical mile", "NMR": "nautical mile radius",
    "NOPT": "no procedure turn required", "NW": "northwest",
    # O
    "OBSC": "obscured", "OBST": "obstruction", "OM": "outer marker", "OPR": "operate",
    "OPS": "operations", "ORIG": "original", "OTS": "out of service", "OVR": "over",
    # P
    "PAEW": "personnel and equipment working",
    "PAPI": "precision approach path indicator", "PAR": "precision approach radar",
    "PARL": "parallel", "PAX": "passengers", "PCL": "pilot controlled lighting",
    "PERM": "permanent", "PJE": "parachute jumping exercise", "PLA": "practice low approach",
    "PLW": "plowed", "PN": "prior notice required", "PPR": "prior permission required",
    "PRKG": "parking", "PROC": "procedure", "PSR": "packed snow on runway",
    "PTCHY": "patchy", "PTN": "procedure turn", "PVT": "private",
    # R
    "RAIL": "runway alignment indicator lights", "RCL": "runway centerline",
    "RCLL": "runway centerline light system", "REDL": "runway edge lights",
    "REIL": "runway end identifier lights", "RELCTD": "relocated", "REP": "report",
    "RLLS": "runway lead-in light system", "RMNDR": "remainder", "RMK": "remark",
    "RNAV": "area navigation", "RPLC": "replace", "RQRD": "required",
    "RSVN": "reservation", "RTE": "route", "RTS": "return to service", "RUF": "rough",
    "RVR": "runway visual range", "RWY": "runway",
    # S
    "SA": "sanded", "SAT": "Saturday", "SB": "southbound",
    "SDF": "simplified directional facility", "SE": "southeast",
    "SFL": "sequenced flashing lights", "SIMUL": "simultaneous",
    "SIR": "packed or compacted snow and ice on runway", "SKED": "scheduled",
    "SLR": "slush on runway", "SN": "snow", "SNBNK": "snowbank", "SPD": "speed",
    "SSALR": "simplified short approach lighting with runway alignment indicator lights",
    "SSALS": "simplified short approach lighting system",
    "SSR": "secondary surveillance radar", "STAR": "standard terminal arrival",
    "SUN": "Sunday", "SVC": "service", "SW": "southwest", "SWEPT": "swept",
    # T
    "TAR": "terminal area surveillance radar", "TDWR": "terminal doppler weather radar",
    "TDZ": "touchdown zone", "TDZL": "touchdown zone lights", "TEMPO": "temporary",
    "TFC": "traffic", "TFR": "temporary flight restriction", "TGL": "touch and go landings",
    "THR": "threshold", "THRU": "through", "THU": "Thursday", "TKOF": "takeoff",
    "TODA": "takeoff distance available", "TORA": "takeoff run available",
    "TRML": "terminal", "TRNG": "training", "TSNT": "transient", "TUE": "Tuesday",
    "TWR": "tower", "TWY": "taxiway",
    # U
    "U/S": "unserviceable", "UAS": "unmanned aircraft system",
    "UAV": "unmanned aerial vehicle", "UFN": "until further notice",
    "UNAVBL": "unavailable", "UNLGTD": "unlighted", "UNMKD": "unmarked",
    "UNMNT": "unmonitored", "UNREL": "unreliable", "UNUSBL": "unusable",
    # V
    "VASI": "visual approach slope indicator", "VDP": "visual descent point",
    "VFR": "visual flight rules", "VIA": "by way of", "VIS": "visibility",
    "VMC": "visual meteorological conditions",
    "VOR": "VHF omnidirectional range", "VORTAC": "VOR and TACAN colocated",
    # W
    "WB": "westbound", "WED": "Wednesday", "WEF": "with effect from",
    "WI": "within", "WIE": "with immediate effect", "WIP": "work in progress",
    "WKDAYS": "Monday through Friday", "WKEND": "Saturday and Sunday",
    "WPT": "waypoint", "WSR": "wet snow on runway", "WTR": "water on runway",
    "WX": "weather", "XCP": "except",
}

# Longest-first so multi-character forms like ``U/S`` win over a bare ``U``.
_ALTERNATION = "|".join(re.escape(k) for k in sorted(CONTRACTIONS, key=len, reverse=True))
_TOKEN_RE = re.compile(rf"\b(?:{_ALTERNATION})\b")


def expand(text: str, *, keep_original: bool = False) -> str:
    """Expand FAA/ICAO contractions in ``text``.

    With ``keep_original`` the contraction is kept and the expansion follows in
    parentheses — useful when a human reads the output next to the raw source.
    """

    def _sub(m: re.Match[str]) -> str:
        token = m.group(0)
        full = CONTRACTIONS[token]
        return f"{token} ({full})" if keep_original else full

    return _TOKEN_RE.sub(_sub, text)


def coverage(text: str) -> float:
    """Fraction of whitespace tokens the dictionary recognises.

    A low value on a NOTAM body is the signal to escalate it to the learned
    extractor rather than trusting the rule output.
    """
    tokens = [t.strip(".,;:()") for t in text.split()]
    tokens = [t for t in tokens if t and not t.isdigit()]
    if not tokens:
        return 0.0
    known = sum(1 for t in tokens if t.upper() in CONTRACTIONS)
    return known / len(tokens)
