"""Rule-based NOTAM parser: raw text in, :class:`NotamRecord` out.

This is the deterministic floor of the extraction stack. It handles the parts
of a NOTAM that are genuinely structured — the ICAO field layout, the Q-code,
the time windows — plus a conservative pass over the free-text ``E)`` field for
the entity patterns that are unambiguous in regex.

It is *not* meant to be complete. The free-text field is where aviation English
gets creative, and the whole point of Sprint 2's fine-tuned token classifier is
to cover what regex cannot. What this module owes that model is an honest
confidence score, so the router knows when to escalate.

Run ``python -m preflight.decode.notam --demo`` to see it work.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from preflight.decode.contractions import coverage, expand
from preflight.decode.qcode import PURPOSE, SCOPE, TRAFFIC, decode_qcode
from preflight.schemas import Entity, EntityState, EntityType, NotamRecord, Phase, Severity

# --------------------------------------------------------------------------
# Structural patterns
# --------------------------------------------------------------------------

_ICAO_HEADER = re.compile(
    r"^\s*([A-Z]\d{4}/\d{2})\s+(NOTAM[NRC])(?:\s+([A-Z]\d{4}/\d{2}))?", re.MULTILINE
)
_US_HEADER = re.compile(
    r"^\s*!([A-Z]{3})\s+(\d{2}/\d{3})\s+([A-Z]{3,4})\s+(.*)", re.DOTALL
)
_FIELD = re.compile(r"\b([QABCDEFG])\)\s*", re.MULTILINE)
_US_WINDOW = re.compile(r"\b(\d{10})-(\d{10}|PERM|UFN)(EST)?\s*$")

_QLINE = re.compile(
    r"^(?P<fir>[A-Z]{4})/(?P<q>Q[A-Z]{4})/(?P<traffic>[IVK]+)/(?P<purpose>[NBOMK]+)/"
    r"(?P<scope>[AEWK]+)/(?P<lower>\d{3})/(?P<upper>\d{3})(?:/(?P<coord>[\d NSEW]+))?"
)
_RADIUS = re.compile(r"(\d{3})$")

# --------------------------------------------------------------------------
# Free-text entity patterns
# --------------------------------------------------------------------------

_RWY_RE = re.compile(r"\bRWY\s+((?:\d{1,2}[LRC]?)(?:/\d{1,2}[LRC]?)*)")
_TWY_RE = re.compile(r"\bTWY\s+([A-Z]{1,3}\d{0,2})")
_BTN_RE = re.compile(
    r"\bBTN\s+(?:TWY\s+)?([A-Z]{1,3}\d{0,2})\s+AND\s+(?:TWY\s+)?([A-Z]{1,3}\d{0,2})"
)

_LIGHTING = (
    "PAPI", "VASI", "MALSR", "MALSF", "MALS", "SSALR", "SSALS", "ALSF-2", "ALSF-1",
    "ALSF", "ODALS", "REIL", "HIRL", "MIRL", "LIRL", "RCLL", "TDZL", "RAIL", "ALS",
    "RLLS", "SFL", "ABN", "PCL",
)
_NAVAIDS = (
    "ILS/DME", "LOC/DME", "VOR/DME", "VORTAC", "TACAN", "ILS", "LOC", "LLZ", "LDA",
    "SDF", "GS", "GP", "DME", "VOR", "NDB", "LOM", "MM", "OM", "IM", "MLS", "RNAV", "GPS",
)
_FACILITY_ALT = "|".join(re.escape(t) for t in sorted(_LIGHTING + _NAVAIDS, key=len, reverse=True))
_FACILITY_RE = re.compile(rf"\b({_FACILITY_ALT})\b")
_LIGHTING_SET = frozenset(_LIGHTING)

_OBST_RE = re.compile(r"\b(OBST|CRANE|TOWER|ANTENNA|MAST)\b")
_AIRSPACE_RE = re.compile(r"\b(TFR|MOA|RESTRICTED AREA|PROHIBITED AREA|DANGER AREA|AIRSPACE)\b")
_APRON_RE = re.compile(r"\b(APRON|APN|RAMP|STAND|GATE)\b")
_SERVICE_RE = re.compile(r"\b(ARFF|FUEL|CUSTOMS|TWR|ATIS|AWOS|ASOS|APP|SVC)\b")

_STATES: tuple[tuple[re.Pattern[str], EntityState], ...] = (
    (re.compile(r"\bCLSD\b|\bCLOSED\b"), EntityState.CLOSED),
    (re.compile(r"\bU/S\b|\bUNSERVICEABLE\b|\bOTS\b|\bINOP\b|\bUNUSBL\b|\bUNAVBL\b"),
     EntityState.UNSERVICEABLE),
    (re.compile(r"\bDISP\b|\bDISPLACED\b|\bRELCTD\b"), EntityState.DISPLACED),
    (re.compile(r"\bACT\b|\bACTIVE\b|\bACTIVATED\b"), EntityState.ACTIVE),
    (re.compile(r"\bLTD\b|\bLIMITED\b|\bRESTRICTED\b|\bPPR\b|\bPN\b"), EntityState.RESTRICTED),
    (re.compile(r"\bAVBL\b|\bAVAILABLE\b|\bRTS\b|\bOPERATIONAL\b"), EntityState.AVAILABLE),
)
_CAUSE_RE = re.compile(r"\bDUE\s+(?:TO\s+)?([A-Z/ ]{2,40}?)(?=\.|,|$)")

# --------------------------------------------------------------------------
# Hazard → phase-of-flight mapping
# --------------------------------------------------------------------------

_PHASES_BY_TYPE: dict[EntityType, tuple[Phase, ...]] = {
    EntityType.RWY: (Phase.TAKEOFF, Phase.LANDING),
    EntityType.TWY: (Phase.TAXI,),
    EntityType.APRON: (Phase.TAXI,),
    EntityType.LIGHTING: (Phase.APPROACH, Phase.LANDING),
    EntityType.NAVAID: (Phase.APPROACH, Phase.ENROUTE),
    EntityType.OBSTACLE: (Phase.TAKEOFF, Phase.APPROACH, Phase.LANDING),
    EntityType.AIRSPACE: (Phase.ENROUTE,),
    EntityType.SERVICE: (Phase.TAXI,),
}


class NotamParseError(ValueError):
    """Raised only when the input is not recognisably a NOTAM at all."""


# --------------------------------------------------------------------------
# Time
# --------------------------------------------------------------------------

def parse_notam_time(value: str) -> datetime | None:
    """Parse a 10-digit ``YYMMDDHHMM`` NOTAM timestamp (always UTC)."""
    value = value.strip().upper().removesuffix("EST").strip()
    if not value or value in {"PERM", "UFN"} or len(value) != 10 or not value.isdigit():
        return None
    yy, mm, dd, hh, mi = (
        int(value[0:2]), int(value[2:4]), int(value[4:6]), int(value[6:8]), int(value[8:10])
    )
    # NOTAM years are two-digit; the window is short enough that a fixed
    # 2000-offset is safe and auditable.
    try:
        return datetime(2000 + yy, mm, dd, hh, mi, tzinfo=UTC)
    except ValueError:
        return None


# --------------------------------------------------------------------------
# Entity extraction
# --------------------------------------------------------------------------

def _state_of(text: str) -> EntityState:
    for pattern, state in _STATES:
        if pattern.search(text):
            return state
    return EntityState.UNKNOWN


def _cause_of(text: str) -> str | None:
    m = _CAUSE_RE.search(text)
    return m.group(1).strip() if m else None


def _sentences(body: str) -> list[tuple[str, int]]:
    """Split the E) field into clauses, keeping each clause's start offset."""
    out: list[tuple[str, int]] = []
    pos = 0
    for chunk in re.split(r"(?<=\.)\s+|\n+", body):
        if chunk.strip():
            idx = body.find(chunk, pos)
            out.append((chunk, idx if idx >= 0 else pos))
            pos = (idx if idx >= 0 else pos) + len(chunk)
    return out or [(body, 0)]


def extract_entities(body: str) -> tuple[Entity, ...]:
    """Pull typed entities out of a NOTAM ``E)`` field.

    Clause-scoped on purpose: a state word applies to the thing named in its own
    clause, which is what keeps ``ALTN RWY 28L AVBL`` from marking 28L closed
    just because a previous clause closed 28R.
    """
    found: list[Entity] = []

    for clause, base in _sentences(body):
        state = _state_of(clause)
        cause = _cause_of(clause)
        rwys = list(_RWY_RE.finditer(clause))

        # A lighting or navaid keyword owns the clause; a runway mention beside
        # it is a qualifier ("PAPI RWY 28L U/S"), not a second entity.
        facility = _FACILITY_RE.search(clause)
        if facility:
            name = facility.group(1)
            ref = f"{name} {rwys[0].group(1)}" if rwys else name
            found.append(Entity(
                type=EntityType.LIGHTING if name in _LIGHTING_SET else EntityType.NAVAID,
                ref=ref, state=state, cause=cause,
                span=(base + facility.start(), base + facility.end()),
            ))
            continue

        if obst := _OBST_RE.search(clause):
            found.append(Entity(
                type=EntityType.OBSTACLE, ref=obst.group(1), state=state, cause=cause,
                detail=clause.strip().rstrip("."),
                span=(base + obst.start(), base + obst.end()),
            ))
            continue

        if air := _AIRSPACE_RE.search(clause):
            found.append(Entity(
                type=EntityType.AIRSPACE, ref=air.group(1),
                state=state if state is not EntityState.UNKNOWN else EntityState.ACTIVE,
                cause=cause, detail=clause.strip().rstrip("."),
                span=(base + air.start(), base + air.end()),
            ))
            continue

        for m in rwys:
            detail = "alternate" if re.search(r"\bALTN\b", clause) else None
            found.append(Entity(
                type=EntityType.RWY, ref=m.group(1), state=state, cause=cause, detail=detail,
                span=(base + m.start(1), base + m.end(1)),
            ))

        twys = list(_TWY_RE.finditer(clause))
        if twys:
            btn = _BTN_RE.search(clause)
            # "TWY B BTN TWY A AND TWY F CLSD" — B is the subject, A and F bound it.
            bounds = {btn.group(1), btn.group(2)} if btn else set()
            subject_seen = False
            for m in twys:
                ref = m.group(1)
                if ref in bounds and subject_seen:
                    continue
                detail = None
                if btn and not subject_seen:
                    detail = f"between {btn.group(1)} and {btn.group(2)}"
                found.append(Entity(
                    type=EntityType.TWY, ref=ref, state=state, cause=cause, detail=detail,
                    span=(base + m.start(1), base + m.end(1)),
                ))
                subject_seen = True
                if btn:
                    break

        if not rwys and not twys and (svc := _SERVICE_RE.search(clause)):
            found.append(Entity(
                type=EntityType.SERVICE, ref=svc.group(1), state=state, cause=cause,
                span=(base + svc.start(), base + svc.end()),
            ))
        elif not rwys and not twys and (apn := _APRON_RE.search(clause)):
            found.append(Entity(
                type=EntityType.APRON, ref=apn.group(1), state=state, cause=cause,
                span=(base + apn.start(), base + apn.end()),
            ))

    return tuple(found)


# --------------------------------------------------------------------------
# Severity and phase
# --------------------------------------------------------------------------

_DEGRADED = {EntityState.CLOSED, EntityState.UNSERVICEABLE, EntityState.DISPLACED}


def infer_severity(entities: tuple[Entity, ...], qcode_severity: str | None) -> Severity:
    """Severity floor from the Q-code, raised (never lowered) by the entities."""
    best = Severity(qcode_severity) if qcode_severity else Severity.INFO
    for e in entities:
        if e.state not in _DEGRADED:
            continue
        if e.type in {EntityType.RWY, EntityType.NAVAID, EntityType.AIRSPACE}:
            candidate = Severity.HIGH
        elif e.type in {EntityType.LIGHTING, EntityType.TWY, EntityType.OBSTACLE}:
            candidate = Severity.MEDIUM
        else:
            candidate = Severity.LOW
        if candidate.rank > best.rank:
            best = candidate
    return best


def infer_phases(entities: tuple[Entity, ...]) -> tuple[Phase, ...]:
    phases: list[Phase] = []
    for e in entities:
        for p in _PHASES_BY_TYPE.get(e.type, ()):
            if p not in phases:
                phases.append(p)
    ground = any(e.type in {EntityType.RWY, EntityType.TWY} for e in entities)
    if ground and Phase.TAXI not in phases:
        phases.insert(0, Phase.TAXI)
    return tuple(phases)


# --------------------------------------------------------------------------
# Top-level parse
# --------------------------------------------------------------------------

def _split_fields(text: str) -> dict[str, str]:
    marks = list(_FIELD.finditer(text))
    fields: dict[str, str] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        fields[m.group(1)] = text[m.end():end].strip()
    return fields


def _parse_icao(raw: str, header: re.Match[str]) -> NotamRecord:
    notam_id, kind_raw, referenced = header.group(1), header.group(2), header.group(3)
    kind = {"NOTAMN": "NEW", "NOTAMR": "REPLACE", "NOTAMC": "CANCEL"}[kind_raw]
    fields = _split_fields(raw[header.end():])

    fir = qcode = traffic = purpose = scope = None
    lower = upper = radius = None
    if q := fields.get("Q"):
        flat = " ".join(q.split())
        if m := _QLINE.match(flat):
            fir = m.group("fir")
            qcode = m.group("q")
            traffic = "/".join(TRAFFIC.get(c, c) for c in m.group("traffic"))
            purpose = "/".join(PURPOSE.get(c, c) for c in m.group("purpose"))
            scope = "/".join(SCOPE.get(c, c) for c in m.group("scope"))
            lower, upper = int(m.group("lower")), int(m.group("upper"))
            coord = m.group("coord")
            if coord and (r := _RADIUS.search(coord.strip())):
                radius = int(r.group(1))

    c_field = fields.get("C", "")
    body = " ".join(fields.get("E", "").split())
    decoded_q = decode_qcode(qcode) if qcode else None
    entities = extract_entities(body)

    a_field = fields.get("A", "").split()
    return NotamRecord(
        id=notam_id,
        icao=a_field[0] if a_field else None,
        fir=fir,
        raw=raw.strip(),
        kind=kind,  # type: ignore[arg-type]
        replaces=referenced,
        effective_from=parse_notam_time(fields.get("B", "")),
        effective_to=parse_notam_time(c_field),
        permanent="PERM" in c_field.upper(),
        estimated_end="EST" in c_field.upper(),
        schedule=fields.get("D") or None,
        qcode=qcode,
        qcode_text=decoded_q.describe() if decoded_q else None,
        traffic=traffic, purpose=purpose, scope=scope,
        lower_fl=lower, upper_fl=upper, radius_nm=radius,
        body=body,
        body_expanded=expand(body),
        entities=entities,
        hazard_class=decoded_q.hazard_class if decoded_q else _hazard_from_entities(entities),
        severity=infer_severity(entities, decoded_q.severity if decoded_q else None),
        phases=infer_phases(entities),
        decoder="rules",
        decode_confidence=_confidence(body, entities, decoded_q is not None),
    )


def _parse_us_domestic(raw: str, header: re.Match[str]) -> NotamRecord:
    accountability, number, location, rest = header.groups()
    rest = " ".join(rest.split())

    eff = exp = None
    permanent = estimated = False
    if w := _US_WINDOW.search(rest):
        eff = parse_notam_time(w.group(1))
        exp = parse_notam_time(w.group(2))
        permanent = w.group(2) in {"PERM", "UFN"}
        estimated = bool(w.group(3))
        rest = rest[: w.start()].strip()

    entities = extract_entities(rest)
    return NotamRecord(
        id=f"!{accountability} {number}",
        icao=f"K{location}" if len(location) == 3 else location,
        raw=raw.strip(),
        effective_from=eff, effective_to=exp,
        permanent=permanent, estimated_end=estimated,
        body=rest,
        body_expanded=expand(rest),
        entities=entities,
        hazard_class=_hazard_from_entities(entities),
        severity=infer_severity(entities, None),
        phases=infer_phases(entities),
        decoder="rules",
        decode_confidence=_confidence(rest, entities, False),
    )


def _hazard_from_entities(entities: tuple[Entity, ...]) -> str:
    if not entities:
        return "other"
    primary = entities[0].type
    if primary is EntityType.RWY:
        return "runway_closure" if entities[0].state is EntityState.CLOSED else "runway"
    return {
        EntityType.TWY: "taxiway",
        EntityType.LIGHTING: "lighting",
        EntityType.NAVAID: "navaid",
        EntityType.OBSTACLE: "obstacle",
        EntityType.AIRSPACE: "airspace_restriction",
        EntityType.APRON: "surface",
        EntityType.SERVICE: "services",
    }.get(primary, "other")


def _confidence(body: str, entities: tuple[Entity, ...], had_qcode: bool) -> float:
    """How much to trust this rule-based parse.

    Deliberately pessimistic. The router escalates anything below ~0.6 to the
    learned extractor, and it is far cheaper to escalate a NOTAM we would have
    got right than to publish one we got wrong.
    """
    if not body:
        return 0.2
    score = 0.35 if had_qcode else 0.15
    if entities:
        score += 0.30
        if all(e.state is not EntityState.UNKNOWN for e in entities):
            score += 0.15
    score += 0.25 * min(coverage(body) / 0.6, 1.0)
    return round(min(score, 0.95), 3)


def parse_notam(raw: str) -> NotamRecord:
    """Parse an ICAO-format or US-domestic-format NOTAM.

    Raises :class:`NotamParseError` only when the text is not a NOTAM at all;
    a NOTAM that parses partially comes back with a low ``decode_confidence``
    rather than an exception, because partial is the normal case.
    """
    if not raw or not raw.strip():
        raise NotamParseError("empty input")
    text = raw.strip()

    if header := _ICAO_HEADER.search(text):
        return _parse_icao(text, header)
    if header := _US_HEADER.match(text):
        return _parse_us_domestic(text, header)
    raise NotamParseError(
        "unrecognised NOTAM format — expected an ICAO header (A1234/26 NOTAMN) "
        "or a US domestic header (!SFO 09/142 SFO ...)"
    )


# --------------------------------------------------------------------------
# Demo
# --------------------------------------------------------------------------

DEMO_NOTAMS = [
    """A1477/26 NOTAMN
Q) KZOA/QMRLC/IV/NBO/A/000/999/3737N12222W005
A) KSFO
B) 2609102300 C) 2609110700
E) RWY 28R CLSD DUE WIP. TWY B BTN TWY A AND TWY F CLSD.
ALTN RWY 28L AVBL. PAPI RWY 28L U/S.""",
    """A0912/26 NOTAMN
Q) KZNY/QICAS/I/NBO/A/000/999/4038N07346W005
A) KJFK B) 2609110400 C) 2609111600EST
E) ILS RWY 22L U/S DUE MAINT.""",
    "!SFO 09/142 SFO TWY A BTN TWY B AND TWY C CLSD 2609102330-2609110700EST",
]


def _demo() -> None:
    for raw in DEMO_NOTAMS:
        rec = parse_notam(raw)
        print("=" * 74)
        print(f"{rec.id}  {rec.icao or '----'}  [{rec.decoder} conf={rec.decode_confidence}]")
        if rec.qcode:
            print(f"  Q-code    {rec.qcode} — {rec.qcode_text}")
        window = f"{rec.effective_from:%Y-%m-%d %H:%MZ}" if rec.effective_from else "?"
        fallback = "PERM" if rec.permanent else "?"
        end = f"{rec.effective_to:%Y-%m-%d %H:%MZ}" if rec.effective_to else fallback
        print(f"  Valid     {window} → {end}{' (est)' if rec.estimated_end else ''}")
        phases = [p.value for p in rec.phases]
        print(f"  Hazard    {rec.hazard_class}  severity={rec.severity}  phases={phases}")
        print(f"  Body      {rec.body}")
        print(f"  Expanded  {rec.body_expanded}")
        print("  Entities:")
        for e in rec.entities:
            extra = f"  — {e.detail}" if e.detail else ""
            print(f"    • {e}{extra}")
    print("=" * 74)


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Decode a NOTAM.")
    ap.add_argument("--demo", action="store_true", help="decode the bundled examples")
    ap.add_argument("text", nargs="?", help="raw NOTAM text")
    args = ap.parse_args()
    if args.demo or not args.text:
        _demo()
    else:
        print(parse_notam(args.text).model_dump_json(indent=2))
