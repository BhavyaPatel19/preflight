"""ICAO NOTAM Q-code taxonomy.

A Q-line looks like:

    Q) KZOA/QMRLC/IV/NBO/A/000/999/3737N12222W005
       |     |     |   |  |  |   |  |
       FIR   code  |   |  |  lower/upper (FL)
                   |   |  scope
                   |   purpose
                   traffic

The five-character Q-code is ``Q`` + a two-letter SUBJECT + a two-letter
CONDITION. ``QMRLC`` = ``MR`` (runway) + ``LC`` (closed).

This module is deliberately plain data plus small pure functions: it is the
deterministic floor underneath the learned extractor, and every entry is
traceable to ICAO Doc 8126 / Annex 15. When the model and the rules disagree,
the rules win on anything decodable here.
"""

from __future__ import annotations

from dataclasses import dataclass

# --------------------------------------------------------------------------
# Q-line positional fields
# --------------------------------------------------------------------------

TRAFFIC = {
    "I": "IFR",
    "V": "VFR",
    "K": "checklist",
}

PURPOSE = {
    "N": "immediate attention",
    "B": "operationally significant, include in briefing",
    "O": "flight operations",
    "M": "miscellaneous",
    "K": "checklist",
}

SCOPE = {
    "A": "aerodrome",
    "E": "en-route",
    "W": "navigation warning",
    "K": "checklist",
}

# --------------------------------------------------------------------------
# SUBJECT (characters 2-3)
# --------------------------------------------------------------------------

SUBJECT: dict[str, str] = {
    # -- Movement and landing area (M) --
    "MA": "movement area",
    "MB": "bearing strength",
    "MC": "clearway",
    "MD": "declared distances",
    "MG": "taxiing guidance system",
    "MH": "runway arresting gear",
    "MK": "parking area",
    "MM": "daylight markings",
    "MN": "apron",
    "MO": "aircraft stands taxilane",
    "MP": "aircraft stands",
    "MR": "runway",
    "MS": "stopway",
    "MT": "threshold",
    "MU": "runway turning bay",
    "MW": "strip / shoulder",
    "MX": "taxiway",
    "MY": "rapid exit taxiway",
    # -- Facilities and services (F) --
    "FA": "aerodrome",
    "FB": "friction measuring device",
    "FC": "ceiling measurement equipment",
    "FD": "docking system",
    "FE": "oxygen",
    "FF": "fire fighting and rescue",
    "FG": "ground movement control",
    "FH": "helicopter alighting area",
    "FI": "aircraft de-icing",
    "FJ": "oils",
    "FL": "landing direction indicator",
    "FM": "meteorological service",
    "FO": "fog dispersal system",
    "FP": "heliport",
    "FS": "snow removal equipment",
    "FT": "transmissometer",
    "FU": "fuel availability",
    "FW": "wind direction indicator",
    "FZ": "customs / immigration",
    # -- Lighting facilities (L) --
    "LA": "approach lighting system",
    "LB": "aerodrome beacon",
    "LC": "runway centre line lights",
    "LD": "landing direction indicator lights",
    "LE": "runway edge lights",
    "LF": "sequenced flashing lights",
    "LH": "high intensity runway lights",
    "LI": "runway end identifier lights",
    "LJ": "runway alignment indicator lights",
    "LK": "CAT II components of approach lighting system",
    "LL": "low intensity runway lights",
    "LM": "medium intensity runway lights",
    "LP": "precision approach path indicator (PAPI)",
    "LR": "all landing area lighting facilities",
    "LS": "stopway lights",
    "LT": "threshold lights",
    "LU": "helicopter approach path indicator",
    "LV": "visual approach slope indicator (VASIS)",
    "LW": "heliport lighting",
    "LX": "taxiway centre line lights",
    "LY": "taxiway edge lights",
    "LZ": "runway touchdown zone lights",
    # -- Communications and surveillance (C) --
    "CA": "air/ground facility",
    "CB": "ADS-B",
    "CC": "ADS-C",
    "CD": "controller-pilot data link (CPDLC)",
    "CE": "en-route surveillance radar",
    "CG": "ground controlled approach system",
    "CL": "selective calling system (SELCAL)",
    "CM": "surface movement radar",
    "CP": "precision approach radar",
    "CR": "surveillance radar element of PAR",
    "CS": "secondary surveillance radar",
    "CT": "terminal area surveillance radar",
    # -- Instrument and microwave landing systems (I) --
    "IC": "instrument landing system (ILS)",
    "ID": "ILS DME",
    "IG": "glide path (ILS)",
    "II": "inner marker",
    "IL": "localizer (ILS)",
    "IM": "middle marker",
    "IN": "localizer (not part of ILS)",
    "IO": "outer marker",
    "IS": "ILS Category I",
    "IT": "ILS Category II",
    "IU": "ILS Category III",
    "IW": "microwave landing system (MLS)",
    "IX": "locator outer (LOM)",
    "IY": "locator middle (LMM)",
    # -- Terminal and en-route navigation (N) --
    "NA": "all radio navigation facilities",
    "NB": "non-directional radio beacon (NDB)",
    "NC": "DECCA",
    "ND": "distance measuring equipment (DME)",
    "NF": "fan marker",
    "NL": "locator",
    "NM": "VOR/DME",
    "NN": "TACAN",
    "NO": "OMEGA",
    "NT": "VORTAC",
    "NV": "VOR",
    "NX": "direction finding station",
    # -- Airspace organisation (A) --
    "AA": "minimum altitude",
    "AC": "Class B/C/D/E surface area",
    "AD": "air defense identification zone (ADIZ)",
    "AE": "control area",
    "AF": "flight information region",
    "AH": "upper control area",
    "AL": "minimum usable flight level",
    "AN": "area navigation route",
    "AO": "oceanic control area",
    "AP": "reporting point",
    "AR": "ATS route",
    "AT": "terminal control area",
    "AU": "upper flight information region",
    "AV": "upper advisory area",
    "AX": "intersection",
    "AZ": "aerodrome traffic zone",
    # -- Air traffic restrictions (R) --
    "RA": "airspace reservation",
    "RD": "danger area",
    "RM": "military operating area",
    "RO": "overflying",
    "RP": "prohibited area",
    "RR": "restricted area",
    "RT": "temporary restricted area",
    # -- Warnings (W) --
    "WA": "air display",
    "WB": "aerobatics",
    "WC": "captive balloon or kite",
    "WD": "demolition of explosives",
    "WE": "exercises",
    "WF": "air refueling",
    "WG": "glider flying",
    "WH": "blasting",
    "WJ": "banner / target towing",
    "WL": "ascent of free balloon",
    "WM": "missile, gun or rocket firing",
    "WP": "parachute jumping / paradropping",
    "WR": "radioactive materials or toxic chemicals",
    "WS": "burning or blowing gas",
    "WT": "mass movement of aircraft",
    "WU": "unmanned aircraft",
    "WV": "formation flight",
    "WW": "significant volcanic activity",
    "WY": "aerial survey",
    "WZ": "model flying",
    # -- Other (O) --
    "OA": "aeronautical information service",
    "OB": "obstacle",
    "OE": "aircraft entry requirements",
    "OL": "obstacle lights",
    "OR": "rescue coordination centre",
}

# --------------------------------------------------------------------------
# CONDITION (characters 4-5)
# --------------------------------------------------------------------------

CONDITION: dict[str, str] = {
    # Availability
    "AC": "withdrawn for maintenance",
    "AD": "available for daylight operation",
    "AF": "flight checked and found reliable",
    "AG": "operating but ground checked only, awaiting flight check",
    "AH": "hours of service now",
    "AK": "resumed normal operation",
    "AL": "operative subject to previously published conditions",
    "AM": "military operations only",
    "AN": "available for night operation",
    "AO": "operational",
    "AP": "available, prior permission required",
    "AR": "available on request",
    "AS": "unserviceable",
    "AU": "not available",
    "AW": "completely withdrawn",
    "AX": "previously promulgated shutdown has been cancelled",
    # Changes
    "CA": "activated",
    "CC": "completed",
    "CD": "deactivated",
    "CE": "erected",
    "CF": "operating frequency changed to",
    "CG": "downgraded to",
    "CH": "changed",
    "CI": "identification or radio call sign changed to",
    "CL": "realigned",
    "CM": "displaced",
    "CN": "cancelled",
    "CO": "operating",
    "CP": "operating on reduced power",
    "CR": "temporarily replaced by",
    "CS": "installed",
    "CT": "on test, do not use",
    # Hazard conditions
    "HA": "braking action",
    "HB": "friction coefficient",
    "HC": "covered by compacted snow",
    "HD": "covered by dry snow",
    "HE": "covered by water",
    "HF": "totally free of snow and ice",
    "HG": "grass cutting in progress",
    "HH": "hazard due to",
    "HI": "covered by ice",
    "HJ": "launch planned",
    "HK": "bird migration in progress",
    "HL": "snow clearance completed",
    "HM": "marked by",
    "HN": "covered by wet snow or slush",
    "HO": "obscured by snow",
    "HP": "snow clearance in progress",
    "HQ": "operation cancelled",
    "HR": "standing water",
    "HS": "sanding in progress",
    "HT": "approach according to signal area only",
    "HU": "launch in progress",
    "HV": "work completed",
    "HW": "work in progress",
    "HX": "concentration of birds",
    "HY": "snow banks exist",
    "HZ": "covered by frozen ruts and ridges",
    # Limitations
    "LA": "operating on auxiliary power supply",
    "LB": "reserved for aircraft based therein",
    "LC": "closed",
    "LD": "unsafe",
    "LE": "operating without auxiliary power supply",
    "LF": "interference from",
    "LG": "operating without identification",
    "LH": "unserviceable for aircraft heavier than",
    "LI": "closed to IFR operations",
    "LK": "operating as a fixed light",
    "LL": "usable for limited length and width",
    "LN": "closed to all night operations",
    "LP": "prohibited to",
    "LR": "aircraft restricted to runways and taxiways",
    "LS": "subject to interruption",
    "LT": "limited to",
    "LV": "closed to VFR operations",
    "LW": "will take place",
    "LX": "operating but caution advised due to",
    # Other
    "XX": "plain language",
    "TT": "trigger NOTAM",
}

#: Condition codes that mean "this thing is not usable".
DEGRADED_CONDITIONS = frozenset(
    {"AS", "AU", "AW", "AC", "LC", "LD", "LI", "LN", "LV", "CD", "CT", "HQ", "CP", "LS"}
)

#: Subject codes whose loss directly threatens a runway operation.
CRITICAL_SUBJECTS = frozenset(
    {
        "MR", "MT", "MS", "MD",                      # runway surface / distances
        "IC", "IG", "IL", "IS", "IT", "IU", "IW",    # precision approach guidance
        "LA", "LP", "LV", "LH", "LE", "LZ", "LT",    # approach & runway lighting
        "RP", "RR", "RT", "RA", "RD",                # airspace restrictions
    }
)

#: Subject prefixes grouped into the hazard taxonomy used across the system.
_HAZARD_BY_PREFIX = {
    "M": "surface",
    "L": "lighting",
    "I": "approach_aids",
    "N": "navaid",
    "C": "comms_surveillance",
    "A": "airspace",
    "R": "airspace_restriction",
    "W": "activity_warning",
    "F": "services",
    "O": "obstacle",
}


@dataclass(frozen=True, slots=True)
class QCode:
    """A decoded five-character Q-code."""

    raw: str
    subject: str
    condition: str
    subject_text: str
    condition_text: str

    @property
    def hazard_class(self) -> str:
        if self.subject == "MR":
            return "runway_closure" if self.condition == "LC" else "runway"
        if self.subject == "MX":
            return "taxiway"
        if self.subject == "OB":
            return "obstacle"
        return _HAZARD_BY_PREFIX.get(self.subject[0], "other")

    @property
    def is_degraded(self) -> bool:
        return self.condition in DEGRADED_CONDITIONS

    @property
    def severity(self) -> str:
        """Coarse severity floor. The briefing layer may raise this, never lower it."""
        if not self.is_degraded:
            return "INFO"
        if self.subject in CRITICAL_SUBJECTS:
            return "HIGH"
        if self.subject[0] in {"M", "I", "N", "C"}:
            return "MEDIUM"
        return "LOW"

    def describe(self) -> str:
        return f"{self.subject_text} — {self.condition_text}"


def decode_qcode(code: str) -> QCode | None:
    """Decode a five-character Q-code such as ``QMRLC``.

    Returns ``None`` for anything that is not a well-formed Q-code, rather than
    raising: malformed NOTAMs are routine and the caller falls back to the
    text layer.
    """
    if not code:
        return None
    code = code.strip().upper()
    if len(code) != 5 or not code.startswith("Q") or not code.isalpha():
        return None

    subject, condition = code[1:3], code[3:5]
    subject_text = SUBJECT.get(subject)
    condition_text = CONDITION.get(condition)
    if subject_text is None and condition_text is None:
        return None

    return QCode(
        raw=code,
        subject=subject,
        condition=condition,
        subject_text=subject_text or f"unknown subject ({subject})",
        condition_text=condition_text or f"unknown condition ({condition})",
    )
