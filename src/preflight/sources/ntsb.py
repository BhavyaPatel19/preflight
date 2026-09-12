"""NTSB aviation accident/incident database.

Source: the NTSB's own bulk download (``avall.zip`` → ``avall.mdb``, an Access
database, 2008 → present). Read with ``mdbtools`` (``mdb-export``), which the
Homebrew formula provides. Tables joined here: ``events`` (when, where,
weather, light, injury), ``narratives`` (factual, analysis, probable cause),
``Findings`` (coded findings, flagged cause vs. factor) and ``Events_Sequence``
(occurrences with phase of flight).

This is the golden-set raw material: each event has a date, a nearest airport,
the weather at the time, a phase of flight, and an investigated finding.
"""

from __future__ import annotations

import csv
import shutil
import subprocess
import zipfile
from collections import defaultdict
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from preflight.config import settings
from preflight.schemas import Phase

URL = "https://data.ntsb.gov/avdata/FileDirectory/DownloadFile?fileID=C%3A%5Cavdata%5Cavall.zip"
TABLES = ("events", "narratives", "Findings", "Events_Sequence")

_NOT_AN_AIRPORT = {"", "PVT", "NONE", "NA", "N/A", "UNK", "UNKN", "PRIVATE"}
_ALASKA = {
    "ANC", "FAI", "JNU", "BET", "OME", "OTZ", "SCC", "ADQ", "KTN", "SIT", "BRW", "MRI", "PAQ",
}
_HAWAII = {"HNL", "OGG", "KOA", "LIH", "ITO", "MKK", "LNY", "JRF"}

# Occurrence descriptions are prefixed with the phase: "Landing-landing roll Runway excursion".
_PHASE_PREFIX: tuple[tuple[str, Phase | None], ...] = (
    ("prior to flight", None), ("pushback", Phase.TAXI), ("taxi", Phase.TAXI),
    ("takeoff", Phase.TAKEOFF), ("initial climb", Phase.CLIMB), ("climb", Phase.CLIMB),
    ("enroute", Phase.ENROUTE), ("maneuvering", None),
    ("approach", Phase.APPROACH), ("landing", Phase.LANDING),
    ("emergency descent", Phase.DESCENT), ("uncontrolled descent", Phase.DESCENT),
    ("descent", Phase.DESCENT), ("post-impact", None), ("other", None),
)


def apt_to_icao(ident: str | None) -> str | None:
    i = (ident or "").strip().upper()
    if i in _NOT_AN_AIRPORT or not i.isalnum():
        return None
    if len(i) == 4 and i.isalpha():
        return i
    if len(i) != 3:
        return None
    if i in _ALASKA:
        return "PA" + i[1:] if i[0] == "A" else "P" + i
    if i in _HAWAII:
        return "PH" + i[1:] if i[0] == "H" else "P" + i
    # Alphanumeric 3-char ids (e.g. "5R2") are small US fields with no ICAO code.
    return "K" + i if i.isalpha() else None


def phase_from_occurrence(description: str | None) -> Phase | None:
    d = (description or "").strip().lower()
    for prefix, phase in _PHASE_PREFIX:
        if d.startswith(prefix):
            return phase
    return None


def parse_mdb_date(value: str | None) -> date | None:
    """mdb-export renders dates as 'MM/DD/YY 0' or 'MM/DD/YY HH:MM:SS'."""
    v = (value or "").strip().split(" ")[0]
    if not v:
        return None
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(v, fmt).date()
        except ValueError:
            continue
    return None


def _hhmm(value: str | None) -> str | None:
    v = (value or "").strip()
    return v.zfill(4) if v.isdigit() and len(v) <= 4 else (v or None)


def _num(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


class Finding(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    description: str
    cause_factor: str | None      # 'C' cause, 'F' factor, per NTSB coding
    in_probable_cause: bool


class NtsbEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    ev_id: str
    ntsb_no: str | None
    kind: str | None                # ACC | INC
    date: date | None
    local_time: str | None          # HHMM
    tz: str | None
    city: str | None
    state: str | None
    icao: str | None
    airport_name: str | None
    lat: float | None
    lon: float | None
    light: str | None
    wx_basic: str | None            # VMC | IMC
    visibility_sm: float | None
    wind_dir: float | None
    wind_kts: float | None
    ceiling_ft: float | None
    highest_injury: str | None
    occurrences: tuple[str, ...]
    phases: tuple[Phase, ...]
    findings: tuple[Finding, ...]
    narrative_prelim: str | None
    narrative_analysis: str | None
    probable_cause: str | None

    @property
    def text(self) -> str:
        parts = [p for p in (self.narrative_prelim, self.narrative_analysis) if p]
        if self.probable_cause:
            parts.append(f"Probable cause: {self.probable_cause}")
        if self.findings:
            parts.append("Findings: " + "; ".join(f.description for f in self.findings))
        if self.occurrences:
            parts.append("Sequence: " + "; ".join(self.occurrences))
        return "\n\n".join(parts)

    @property
    def title(self) -> str:
        where = ", ".join(p for p in (self.city, self.state) if p)
        return f"{self.ntsb_no or self.ev_id} — {where} — {self.date or '?'}"[:200]

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "ntsb_no": self.ntsb_no, "kind": self.kind, "local_time": self.local_time,
            "tz": self.tz, "city": self.city, "state": self.state,
            "airport_name": self.airport_name,
            "lat": self.lat, "lon": self.lon, "light": self.light, "wx_basic": self.wx_basic,
            "visibility_sm": self.visibility_sm, "wind_dir": self.wind_dir,
            "wind_kts": self.wind_kts, "ceiling_ft": self.ceiling_ft,
            "highest_injury": self.highest_injury,
            "occurrences": list(self.occurrences), "phases": [p.value for p in self.phases],
            "findings": [f.model_dump() for f in self.findings],
        }


# --------------------------------------------------------------------------
# Files
# --------------------------------------------------------------------------

def raw_dir() -> Path:
    return settings().archive_dir / "ntsb"


def ensure_mdb(*, client: httpx.Client | None = None) -> Path:
    """Download and unzip avall.zip if the .mdb is not already present."""
    d = raw_dir()
    mdb = d / "avall.mdb"
    if mdb.exists():
        return mdb
    d.mkdir(parents=True, exist_ok=True)
    z = d / "avall.zip"
    if not z.exists():
        c = client or httpx.Client(timeout=120.0, follow_redirects=True)
        part = z.with_suffix(".part")
        with c.stream("GET", URL) as r, part.open("wb") as f:
            r.raise_for_status()
            for chunk in r.iter_bytes():
                f.write(chunk)
        z.with_suffix(".part").rename(z)
    with zipfile.ZipFile(z) as zf:
        zf.extractall(d)
    return mdb


def export_table(table: str, *, mdb: Path | None = None) -> Path:
    """``mdb-export`` one table to CSV in the raw dir (cached)."""
    if shutil.which("mdb-export") is None:
        raise RuntimeError("mdb-export not found: brew install mdbtools")
    out = raw_dir() / f"{table}.csv"
    if out.exists() and out.stat().st_size > 0:
        return out
    src = mdb or ensure_mdb()
    with out.with_suffix(".part").open("w") as f:
        subprocess.run(["mdb-export", str(src), table], check=True, stdout=f)
    out.with_suffix(".part").rename(out)
    return out


def _rows(path: Path) -> Iterator[dict[str, str]]:
    with path.open(encoding="utf-8", errors="replace", newline="") as f:
        yield from csv.DictReader(f)


# --------------------------------------------------------------------------
# Assembly
# --------------------------------------------------------------------------

def build_event(
    ev: dict[str, str],
    narrative: dict[str, str] | None,
    findings: list[dict[str, str]],
    sequence: list[dict[str, str]],
) -> NtsbEvent:
    occurrences = tuple(
        s["Occurrence_Description"].strip()
        for s in sequence if s.get("Occurrence_Description")
    )
    phases: list[Phase] = []
    for o in occurrences:
        p = phase_from_occurrence(o)
        if p and p not in phases:
            phases.append(p)
    n = narrative or {}
    return NtsbEvent(
        ev_id=ev["ev_id"].strip(),
        ntsb_no=ev.get("ntsb_no") or None,
        kind=ev.get("ev_type") or None,
        date=parse_mdb_date(ev.get("ev_date")),
        local_time=_hhmm(ev.get("ev_time")),
        tz=(ev.get("ev_tmzn") or "").strip() or None,
        city=ev.get("ev_city") or None,
        state=ev.get("ev_state") or None,
        icao=apt_to_icao(ev.get("ev_nr_apt_id")),
        airport_name=ev.get("apt_name") or None,
        lat=_num(ev.get("dec_latitude")),
        lon=_num(ev.get("dec_longitude")),
        light=ev.get("light_cond") or None,
        wx_basic=ev.get("wx_cond_basic") or None,
        visibility_sm=_num(ev.get("vis_sm")),
        wind_dir=_num(ev.get("wind_dir_deg")),
        wind_kts=_num(ev.get("wind_vel_kts")),
        ceiling_ft=_num(ev.get("sky_cond_ceil")),
        highest_injury=ev.get("ev_highest_injury") or None,
        occurrences=occurrences,
        phases=tuple(phases),
        findings=tuple(
            Finding(
                code=f.get("finding_code", "").strip(),
                description=f.get("finding_description", "").strip(),
                cause_factor=(f.get("Cause_Factor") or "").strip() or None,
                in_probable_cause=(f.get("cm_inPc") or "").strip() in {"1", "True", "true"},
            )
            for f in findings if f.get("finding_description")
        ),
        narrative_prelim=(n.get("narr_accp") or "").strip() or None,
        narrative_analysis=(n.get("narr_accf") or "").strip() or None,
        probable_cause=(n.get("narr_cause") or "").strip() or None,
    )


def iter_events(*, since: date | None = None) -> Iterator[NtsbEvent]:
    """All events with a narrative, oldest first. Exports tables on first call."""
    paths = {t: export_table(t) for t in TABLES}

    narratives: dict[str, dict[str, str]] = {}
    for r in _rows(paths["narratives"]):
        # First aircraft's narrative is the event narrative.
        if r.get("Aircraft_Key", "1").strip() in {"1", ""} or r["ev_id"] not in narratives:
            narratives[r["ev_id"]] = r
    findings: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in _rows(paths["Findings"]):
        findings[r["ev_id"]].append(r)
    sequence: dict[str, list[dict[str, str]]] = defaultdict(list)
    for r in _rows(paths["Events_Sequence"]):
        sequence[r["ev_id"]].append(r)
    for ev_id in sequence:
        sequence[ev_id].sort(key=lambda s: int(s.get("Occurrence_No") or 0))

    events = [r for r in _rows(paths["events"]) if r.get("ev_id")]
    events.sort(key=lambda r: parse_mdb_date(r.get("ev_date")) or date.min)
    for ev in events:
        d = parse_mdb_date(ev.get("ev_date"))
        if since and (d is None or d < since):
            continue
        n = narratives.get(ev["ev_id"])
        if not n or not (n.get("narr_accp") or n.get("narr_accf") or n.get("narr_cause")):
            continue
        yield build_event(ev, n, findings.get(ev["ev_id"], []), sequence.get(ev["ev_id"], []))
