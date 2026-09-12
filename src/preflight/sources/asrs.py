"""NASA ASRS incident reports.

Source: ``elihoole/asrs-aviation-reports`` on the Hugging Face Hub — 47,723
reports exported from NASA's Aviation Safety Reporting System with the full
ASRS field schema. The packaging is Apache-2.0; the underlying reports are
US-government public domain. Files are JSONL; we stream them to the raw
archive and parse the handful of fields the corpus needs.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from preflight.config import settings
from preflight.schemas import Phase

REPO = "elihoole/asrs-aviation-reports"
_BASE = f"https://huggingface.co/datasets/{REPO}/resolve/main"
SPLITS = ("train", "validation", "test")

# ASRS "Flight Phase" vocabulary → our phase enum. Unmapped values are dropped.
_PHASES: dict[str, Phase] = {
    "taxi": Phase.TAXI,
    "takeoff / launch": Phase.TAKEOFF, "takeoff": Phase.TAKEOFF,
    "other rejected takeoff": Phase.TAKEOFF,
    "initial climb": Phase.CLIMB, "climb": Phase.CLIMB,
    "cruise": Phase.ENROUTE,
    "descent": Phase.DESCENT,
    "initial approach": Phase.APPROACH, "final approach": Phase.APPROACH,
    "landing": Phase.LANDING, "other go around": Phase.APPROACH, "other go-around": Phase.APPROACH,
}

# Locale references look like "SFO.Airport", "ZMP.ARTCC", "ZZZ.Airport" (anonymised).
_LOCALE = re.compile(r"^([A-Z0-9]{3,4})\.(Airport|Tower|TRACON|ARTCC)$", re.I)
# US 3-letter FAA ids map to ICAO with a region prefix; ZZZ is ASRS's anonymiser.
_ALASKA = {"ANC", "FAI", "JNU", "BET", "OME", "OTZ", "SCC", "ADQ", "KTN", "SIT", "BRW"}
_HAWAII = {"HNL", "OGG", "KOA", "LIH", "ITO", "MKK", "LNY"}


def locale_to_icao(locale: str | None) -> str | None:
    if not locale:
        return None
    m = _LOCALE.match(locale.strip())
    if not m or m.group(2).lower() != "airport":
        return None
    ident = m.group(1).upper()
    if ident.startswith("ZZZ") or len(ident) not in (3, 4):
        return None
    if len(ident) == 4:
        return ident
    if ident in _ALASKA:
        return "PA" + ident[1:] if ident[0] == "A" else "P" + ident
    if ident in _HAWAII:
        return "PH" + ident[1:] if ident[0] == "H" else "P" + ident
    return "K" + ident


def phases_from(value: str | None) -> tuple[Phase, ...]:
    out: list[Phase] = []
    for part in (value or "").split(";"):
        p = _PHASES.get(part.strip().lower())
        if p and p not in out:
            out.append(p)
    return tuple(out)


def _yyyymm(value: str | None) -> date | None:
    v = (value or "").strip()
    if len(v) == 6 and v.isdigit():
        try:
            return date(int(v[:4]), int(v[4:]), 1)
        except ValueError:
            return None
    return None


class AsrsReport(BaseModel):
    model_config = ConfigDict(frozen=True)

    acn: str
    published: date | None
    icao: str | None
    locale: str | None
    phases: tuple[Phase, ...]
    anomaly: str | None
    primary_problem: str | None
    human_factors: str | None
    narrative: str
    synopsis: str | None

    @property
    def text(self) -> str:
        """What gets chunked and embedded: narrative(s), then the expert synopsis."""
        parts = [self.narrative]
        if self.synopsis:
            parts.append(f"Synopsis: {self.synopsis}")
        return "\n\n".join(parts)

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "locale": self.locale, "anomaly": self.anomaly,
            "primary_problem": self.primary_problem, "human_factors": self.human_factors,
            "phases": [p.value for p in self.phases],
        }


def _clean(value: Any) -> str | None:
    s = str(value).strip() if value is not None else ""
    return s or None


def parse_row(row: dict[str, Any]) -> AsrsReport | None:
    """One JSONL row → report. Returns None when there is no usable narrative."""
    n1 = _clean(row.get("Report 1_Narrative"))
    n2 = _clean(row.get("Report 2_Narrative"))
    if n2 and n2.lower().startswith("[report narrative contained no additional"):
        n2 = None
    narrative = "\n\n".join(p for p in (n1, n2) if p)
    acn = _clean(row.get("acn_num_ACN"))
    if not acn or not narrative:
        return None
    locale = _clean(row.get("Place_Locale Reference"))
    return AsrsReport(
        acn=acn,
        published=_yyyymm(_clean(row.get("Time_Date"))),
        icao=locale_to_icao(locale),
        locale=locale,
        phases=phases_from(_clean(row.get("Aircraft 1_Flight Phase")) or
                           _clean(row.get("Aircraft 1.9_Flight Phase"))),
        anomaly=_clean(row.get("Events_Anomaly")),
        primary_problem=_clean(row.get("Assessments.1_Primary Problem")),
        human_factors=_clean(row.get("Person 1.7_Human Factors")),
        narrative=narrative,
        synopsis=_clean(row.get("Report 1.2_Synopsis")),
    )


def local_path(split: str) -> Path:
    return settings().archive_dir / "asrs" / f"asrs-aviation-reports-{split}.jsonl"


def download(split: str, *, client: httpx.Client | None = None) -> Path:
    """Fetch one split to the raw archive if not already present."""
    path = local_path(split)
    if path.exists() and path.stat().st_size > 0:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    c = client or httpx.Client(timeout=60.0, follow_redirects=True)
    tmp = path.with_suffix(".part")
    with c.stream("GET", f"{_BASE}/{path.name}") as r:
        r.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes():
                f.write(chunk)
    tmp.rename(path)
    return path


def iter_reports(path: Path) -> Iterator[AsrsReport]:
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rep = parse_row(json.loads(line))
            if rep is not None:
                yield rep
