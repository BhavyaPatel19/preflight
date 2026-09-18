from __future__ import annotations

from datetime import UTC, datetime, timedelta
from time import perf_counter
from typing import Any, Literal

from psycopg import Connection

from preflight.config import settings
from preflight.db import notams as ndb
from preflight.db import runs as rdb
from preflight.db import weather as wdb
from preflight.decode.contractions import expand
from preflight.forecast.delay import climatology, local_time
from preflight.schemas import (
    Abstention,
    Briefing,
    Citation,
    Claim,
    EntityState,
    EntityType,
    Finding,
    FlightRequest,
    NotamRecord,
    Phase,
    Severity,
)

Role = Literal["departure", "destination", "alternate"]

_PHASES_BY_ROLE: dict[Role, tuple[Phase, ...]] = {
    "departure": (Phase.TAXI, Phase.TAKEOFF, Phase.CLIMB),
    "destination": (Phase.DESCENT, Phase.APPROACH, Phase.LANDING),
    "alternate": (Phase.APPROACH, Phase.LANDING),
}

_CATEGORY = {
    "runway_closure": "runway", "runway": "runway", "taxiway": "taxiway",
    "lighting": "lighting", "approach_aids": "approach aids", "navaid": "navaid",
    "airspace_restriction": "airspace", "airspace": "airspace", "obstacle": "obstacle",
    "surface": "surface", "services": "services", "comms_surveillance": "comms",
    "activity_warning": "activity", "wildlife": "wildlife",
}

_WX_SEVERITY = {
    "LIFR": Severity.HIGH, "IFR": Severity.MEDIUM, "MVFR": Severity.LOW, "VFR": Severity.INFO,
}

_STATE_WORD = {
    EntityState.CLOSED: "closed",
    EntityState.UNSERVICEABLE: "unserviceable",
    EntityState.DISPLACED: "displaced",
    EntityState.RESTRICTED: "restricted",
    EntityState.ACTIVE: "active",
    EntityState.AVAILABLE: "available",
    EntityState.UNKNOWN: "affected",
}

_TYPE_WORD = {
    EntityType.RWY: "Runway", EntityType.TWY: "Taxiway", EntityType.NAVAID: "",
    EntityType.LIGHTING: "", EntityType.OBSTACLE: "Obstacle", EntityType.AIRSPACE: "",
    EntityType.APRON: "Apron", EntityType.SERVICE: "",
}


# --------------------------------------------------------------------------
# Windows
# --------------------------------------------------------------------------

def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def windows(req: FlightRequest) -> list[tuple[str, Role, datetime, datetime]]:
    """(icao, role, start, end) for every airport the flight touches.

    Departure hazards matter around off-block. Without a flight time, the
    destination and alternates are checked across a conservative window.
    """
    t0 = _utc(req.off_block)
    ete = timedelta(hours=settings().default_ete_window_hours)
    out: list[tuple[str, Role, datetime, datetime]] = [
        (req.departure, "departure", t0 - timedelta(minutes=30), t0 + timedelta(minutes=90)),
        (req.destination, "destination", t0 + timedelta(minutes=30), t0 + ete),
    ]
    out.extend((alt, "alternate", t0 + timedelta(minutes=30), t0 + ete) for alt in req.alternates)
    return out


# --------------------------------------------------------------------------
# NOTAM findings
# --------------------------------------------------------------------------

def _fmt(dt: datetime | None) -> str:
    """Always UTC with a Z — the driver may hand back the session timezone."""
    return f"{_utc(dt):%d %b %H%M}Z" if dt else "?"


def headline(rec: NotamRecord) -> str:
    """One plain sentence from the decoded entities, never from the raw text."""
    benign = {EntityState.AVAILABLE, EntityState.UNKNOWN}
    degraded = [e for e in rec.entities if e.state not in benign]
    e = degraded[0] if degraded else (rec.entities[0] if rec.entities else None)
    if e is None:
        return rec.qcode_text or rec.body_expanded[:90] or rec.body[:90]

    noun = f"{_TYPE_WORD[e.type]} {e.ref}".strip()
    text = f"{noun} {_STATE_WORD[e.state]}"
    if e.detail and e.detail != "alternate":
        text += f" {e.detail}"
    if e.cause:
        text += f" ({expand(e.cause).lower()})"
    if rec.permanent:
        text += ", permanent"
    elif rec.effective_to:
        text += f" until {_fmt(rec.effective_to)}"
        if rec.estimated_end:
            text += " (est)"
    return text


def _notam_quote(rec: NotamRecord) -> str:
    """The evidence a NOTAM claim rests on: the body plus its validity window."""
    if rec.permanent:
        valid = f"valid from {_fmt(rec.effective_from)}, permanent"
    else:
        valid = f"valid {_fmt(rec.effective_from)} to {_fmt(rec.effective_to)}"
        if rec.estimated_end:
            valid += " (estimated)"
    return f"{rec.body[:220]} — {valid}."


def _claim(rec: NotamRecord, text: str) -> Claim:
    return Claim(
        text=text,
        citations=(Citation(
            kind="notam", ref=rec.id, issued_at=rec.effective_from, quote=_notam_quote(rec)
        ),),
    )


def notam_findings(icao: str, role: Role, records: list[NotamRecord]) -> list[Finding]:
    findings: list[Finding] = []
    minor: list[NotamRecord] = []

    for rec in records:
        if rec.severity in {Severity.HIGH, Severity.MEDIUM}:
            relevant = tuple(p for p in rec.phases if p in _PHASES_BY_ROLE[role])
            phases = relevant or _PHASES_BY_ROLE[role]
            findings.append(Finding(
                category=_CATEGORY.get(rec.hazard_class, "notam"),
                severity=rec.severity,
                phases=phases,
                headline=f"{icao}: {headline(rec)}",
                claims=(_claim(rec, f"{icao} — {headline(rec)}."),),
                airport=icao,
            ))
        else:
            minor.append(rec)

    # Low-severity NOTAMs are collapsed, not hidden: one INFO finding citing all of them.
    if minor:
        findings.append(Finding(
            category="notam",
            severity=Severity.INFO,
            phases=_PHASES_BY_ROLE[role],
            airport=icao,
            headline=f"{icao}: {len(minor)} further NOTAM{'s' if len(minor) != 1 else ''} "
                     "in the window",
            claims=(Claim(
                text=f"{icao} has {len(minor)} low-severity NOTAM(s) in the window: "
                     + "; ".join(headline(r) for r in minor[:6])
                     + (" …" if len(minor) > 6 else "") + ".",
                citations=tuple(
                    Citation(kind="notam", ref=r.id, issued_at=r.effective_from,
                             quote=_notam_quote(r))
                    for r in minor
                ),
            ),),
        ))
    return findings


# --------------------------------------------------------------------------
# Weather findings
# --------------------------------------------------------------------------

def _wind_severity(parsed: dict[str, Any]) -> Severity:
    """Gusts and strong surface wind are the most common briefable hazard in the NTSB set."""
    wind = float(parsed.get("wind_kt") or 0)
    gust = float(parsed.get("gust_kt") or 0)
    if gust >= 35 or wind >= 30:
        return Severity.MEDIUM
    if gust >= 25 or wind >= 20:
        return Severity.LOW
    return Severity.INFO


def _metar_summary(parsed: dict[str, Any]) -> str:
    bits: list[str] = []
    if parsed.get("wind_kt") is not None:
        if not parsed["wind_kt"]:
            bits.append("wind calm")
        else:
            wdir = f"{parsed['wind_dir']:03d}" if parsed.get("wind_dir") is not None else "VRB"
            w = f"wind {wdir}/{parsed['wind_kt']}"
            if parsed.get("gust_kt"):
                w += f"G{parsed['gust_kt']}"
            bits.append(w + " kt")
    if parsed.get("visibility_sm") is not None:
        v = parsed["visibility_sm"]
        bits.append(f"vis {int(v) if float(v).is_integer() else v} SM")
    if parsed.get("ceiling_ft") is not None:
        bits.append(f"ceiling {parsed['ceiling_ft']} ft")
    if parsed.get("wx"):
        bits.append(str(parsed["wx"]))
    return ", ".join(bits)


def weather_findings(
    icao: str,
    role: Role,
    metar: wdb.WeatherRow | None,
    taf: wdb.WeatherRow | None,
    *,
    now: datetime,
    window_start: datetime,
    window_end: datetime,
) -> tuple[list[Finding], list[Abstention]]:
    findings: list[Finding] = []
    abstain: list[Abstention] = []
    stale_after = timedelta(minutes=settings().metar_stale_after_minutes)

    if metar is None:
        abstain.append(Abstention(
            topic=f"{icao} current weather", reason="no_coverage",
            detail=f"No METAR on record for {icao}.",
        ))
    elif now - _utc(metar.issued_at) > stale_after:
        age = int((now - _utc(metar.issued_at)).total_seconds() // 60)
        abstain.append(Abstention(
            topic=f"{icao} current weather", reason="stale_source",
            detail=f"Latest METAR for {icao} is {age} min old (threshold "
                   f"{settings().metar_stale_after_minutes} min); not cited.",
        ))
    else:
        cat = str(metar.parsed.get("flight_category") or "").upper()
        sev = _WX_SEVERITY.get(cat, Severity.INFO)
        sev = max(sev, _wind_severity(metar.parsed), key=lambda s: s.rank)
        summary = _metar_summary(metar.parsed)
        label = cat or "conditions"
        findings.append(Finding(
            category="weather",
            severity=sev,
            phases=_PHASES_BY_ROLE[role],
            airport=icao,
            headline=f"{icao}: {label}" + (f" — {summary}" if summary else ""),
            claims=(Claim(
                text=f"{icao} is reporting {label} at {_fmt(_utc(metar.issued_at))}"
                     + (f": {summary}." if summary else "."),
                citations=(Citation(
                    kind="metar", ref=f"{icao}@{_utc(metar.issued_at):%d%H%M}Z",
                    issued_at=metar.issued_at,
                    quote=f"{metar.raw} — decoded: {icao} reporting {label} at "
                          f"{_fmt(_utc(metar.issued_at))}" + (f", {summary}" if summary else "")
                          + ".",
                ),),
            ),),
        ))

    # Forecast coverage: a TAF that does not span the window is a gap, not a fact.
    if role != "departure":
        covers = (
            taf is not None and taf.valid_from is not None and taf.valid_to is not None
            and _utc(taf.valid_from) <= window_end and _utc(taf.valid_to) >= window_start
        )
        if not covers:
            abstain.append(Abstention(
                topic=f"{icao} forecast", reason="no_coverage",
                detail=f"No TAF for {icao} covers {_fmt(window_start)}–{_fmt(window_end)}.",
            ))
        else:
            assert taf is not None and taf.valid_from is not None and taf.valid_to is not None
            valid = f"{_fmt(_utc(taf.valid_from))}–{_fmt(_utc(taf.valid_to))}"
            findings.append(Finding(
                category="forecast",
                severity=Severity.INFO,
                phases=_PHASES_BY_ROLE[role],
                airport=icao,
                headline=f"{icao}: TAF valid {valid}",
                claims=(Claim(
                    text=f"A TAF for {icao} issued {_fmt(_utc(taf.issued_at))} covers "
                         "the arrival window.",
                    citations=(Citation(
                        kind="taf", ref=f"{icao}@{_utc(taf.issued_at):%d%H%M}Z",
                        issued_at=taf.issued_at, quote=taf.raw,
                    ),),
                ),),
            ))
    return findings, abstain


# --------------------------------------------------------------------------
# Delay climatology
# --------------------------------------------------------------------------

def delay_finding(
    conn: Connection[Any], icao: str, role: Role, arrival_utc: datetime
) -> Finding | None:
    """Typical arrival delay for this airport at this weekday and hour, from BTS history.

    Climatology, and labelled as such: BTS data lands with a ~3-month lag, so a
    model forecast for a flight next week would be theater. The eval compares
    the model against this baseline; the briefing cites what it can stand behind.
    """
    if role == "departure":
        return None
    local = local_time(icao, arrival_utc)
    if local is None:
        return None
    c = climatology(conn, icao, local)
    if c is None:
        return None
    if c.p50 >= 60 or c.p90 >= 120:
        sev = Severity.MEDIUM
    elif c.p50 >= 30 or c.p90 >= 60:
        sev = Severity.LOW
    else:
        sev = Severity.INFO
    day = local.strftime("%a")
    summary = (f"typical arrival delay {day} {local:%H}:00 local — median {c.p50:.0f} min, "
               f"80% within {c.p10:.0f}…{c.p90:.0f}")
    return Finding(
        category="delay", severity=sev, phases=(Phase.APPROACH, Phase.LANDING),
        headline=f"{icao}: {summary}", airport=icao,
        claims=(Claim(
            text=f"Over {c.samples} {day} {local:%H}:00 hours in the BTS record "
                 f"({c.history_from:%b %Y}–{c.history_to:%b %Y}), median arrival delay at {icao} "
                 f"was {c.p50:.0f} min and 80% of hours fell within {c.p10:.0f}…{c.p90:.0f} min "
                 f"(~{c.flights_per_hour:.0f} arrivals/h). Climatology, not a forecast.",
            citations=(Citation(
                kind="forecast", ref=f"climatology:{icao}:{day}{local:%H}",
                quote=f"BTS On-Time Performance for {icao}, {c.samples} {day} {local:%H}:00 "
                      f"hours from {c.history_from:%b %Y} to {c.history_to:%b %Y}: median arrival "
                      f"delay {c.p50:.0f} min; 80% of hours fell within {c.p10:.0f} to {c.p90:.0f} "
                      f"min (10th to 90th percentile); about {c.flights_per_hour:.0f} arrivals per "
                      "hour. This is climatology — historical typical values — not a forecast.",
            ),),
        ),),
    )


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_briefing(
    conn: Connection[Any], req: FlightRequest, *, now: datetime | None = None
) -> Briefing:
    """Deterministic briefing from what is in the database right now."""
    t_start = perf_counter()
    now = _utc(now or datetime.now(UTC))
    findings: list[Finding] = []
    abstentions: list[Abstention] = []
    considered = 0

    for icao, role, start, end in windows(req):
        records = ndb.active_during(conn, icao, start, end)
        considered += len(records)
        findings.extend(notam_findings(icao, role, records))
        # Nothing in force is a finding of sorts; nothing ever archived is a gap. A briefing
        # that is silent about NOTAMs because it never had any reads as "no hazards".
        if not records and ndb.count_for(conn, icao) == 0:
            abstentions.append(Abstention(
                topic=f"{icao} NOTAMs", reason="no_coverage",
                detail=f"No NOTAMs on record for {icao}; the archive does not cover this "
                       "airport, so NOTAM hazards were not assessed.",
            ))

        metar = wdb.latest(conn, icao, "METAR", as_of=now)
        taf = wdb.latest(conn, icao, "TAF", as_of=now)
        considered += (metar is not None) + (taf is not None)
        wx, gaps = weather_findings(
            icao, role, metar, taf, now=now, window_start=start, window_end=end
        )
        findings.extend(wx)
        abstentions.extend(gaps)

        if role != "departure":
            ete = timedelta(minutes=req.ete_minutes) if req.ete_minutes else timedelta(hours=3)
            delay = delay_finding(conn, icao, role, _utc(req.off_block) + ete)
            if delay is not None:
                findings.append(delay)
                considered += 1
            else:
                abstentions.append(Abstention(
                    topic=f"{icao} arrival delay", reason="no_coverage",
                    detail=f"No arrival-delay history for {icao} in the BTS record; no "
                           "delay climatology given.",
                ))

    # NOTAMs the decoder rejected are not in the table at all, so no airport loop can see
    # them. The ingest run counted them; say so once, for the whole briefing.
    last = rdb.latest(conn, "notams")
    if last is not None and int(last.counts.get("unparseable", 0)) > 0:
        n = int(last.counts["unparseable"])
        abstentions.append(Abstention(
            topic="NOTAM decoding", reason="parse_failure",
            detail=f"{n} NOTAM{'s' if n != 1 else ''} in the latest fetch ({last.source}, "
                   f"{_fmt(_utc(last.finished_at))}) could not be decoded and "
                   f"{'are' if n != 1 else 'is'} not assessed.",
        ))

    return Briefing(
        request=req,
        generated_at=now,
        findings=tuple(sorted(findings, key=lambda f: f.sort_key)),
        abstentions=tuple(abstentions),
        sources_considered=considered,
        latency_ms=int((perf_counter() - t_start) * 1000),
    )
