"""Typed contracts for the whole system.

Everything that crosses a module boundary is one of these. The briefing schema
in particular is strict on purpose: a claim that cannot name its source is not
allowed to exist, which is what makes the grounding evaluation possible.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

ICAO = Annotated[str, Field(pattern=r"^[A-Z]{4}$", description="ICAO location indicator")]


class Severity(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INFO = "INFO"

    @property
    def rank(self) -> int:
        return {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "INFO": 0}[self.value]


class Phase(StrEnum):
    """Phase of flight a hazard bears on. Drives ranking, not just display."""

    TAXI = "taxi"
    TAKEOFF = "takeoff"
    CLIMB = "climb"
    ENROUTE = "enroute"
    DESCENT = "descent"
    APPROACH = "approach"
    LANDING = "landing"


class EntityType(StrEnum):
    RWY = "RWY"
    TWY = "TWY"
    NAVAID = "NAVAID"
    LIGHTING = "LIGHTING"
    OBSTACLE = "OBSTACLE"
    AIRSPACE = "AIRSPACE"
    SERVICE = "SERVICE"
    APRON = "APRON"


class EntityState(StrEnum):
    CLOSED = "CLOSED"
    UNSERVICEABLE = "UNSERVICEABLE"
    AVAILABLE = "AVAILABLE"
    RESTRICTED = "RESTRICTED"
    DISPLACED = "DISPLACED"
    ACTIVE = "ACTIVE"
    UNKNOWN = "UNKNOWN"


class Entity(BaseModel):
    """One thing a NOTAM says something about.

    This is the target schema for the fine-tuned token classifier in Sprint 2;
    the rule layer in Sprint 1 populates the same shape so the two are
    directly comparable on the same eval set.
    """

    model_config = ConfigDict(frozen=True)

    type: EntityType
    ref: str = Field(description="Identifier as written, e.g. '28R', 'TWY B', 'PAPI 28L'")
    state: EntityState = EntityState.UNKNOWN
    cause: str | None = Field(default=None, description="e.g. 'WIP', 'SNOW'")
    detail: str | None = None
    span: tuple[int, int] | None = Field(
        default=None, description="Character offsets in the source text, for citation highlighting"
    )

    def __str__(self) -> str:
        bits = [self.type.value, self.ref, self.state.value]
        if self.cause:
            bits.append(f"({self.cause})")
        return " ".join(bits)


class NotamRecord(BaseModel):
    """A decoded NOTAM. The unit of evidence for most of the briefing."""

    model_config = ConfigDict(frozen=True)

    id: str
    icao: ICAO | None = None
    fir: str | None = None
    raw: str

    kind: Literal["NEW", "REPLACE", "CANCEL"] = "NEW"
    replaces: str | None = None

    effective_from: datetime | None = None
    effective_to: datetime | None = None
    permanent: bool = False
    estimated_end: bool = False
    schedule: str | None = Field(default=None, description="D) field — recurring time window")

    qcode: str | None = None
    qcode_text: str | None = None
    traffic: str | None = None
    purpose: str | None = None
    scope: str | None = None
    lower_fl: int | None = None
    upper_fl: int | None = None
    radius_nm: int | None = None

    body: str = Field(default="", description="E) field, raw")
    body_expanded: str = Field(default="", description="E) field with contractions expanded")
    entities: tuple[Entity, ...] = ()

    hazard_class: str = "other"
    severity: Severity = Severity.INFO
    phases: tuple[Phase, ...] = ()

    decoder: Literal["rules", "model", "llm", "hybrid"] = "rules"
    decode_confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @field_validator("id")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("NOTAM id must not be empty")
        return v.strip()

    def active_at(self, when: datetime) -> bool:
        """Is this NOTAM in force at ``when``? Missing bounds are treated as open."""
        started = self.effective_from is None or when >= self.effective_from
        expired = (
            self.effective_to is not None
            and not self.permanent
            and when > self.effective_to
        )
        return started and not expired


class Citation(BaseModel):
    """A pointer from a claim back to the record that supports it.

    ``kind`` and ``ref`` together must be enough to retrieve the source text,
    because the verifier re-fetches it to check entailment.
    """

    model_config = ConfigDict(frozen=True)

    kind: Literal[
        "notam", "metar", "taf", "pirep", "sigmet", "asrs", "ntsb", "forecast", "far_aim",
        "ops_note",
    ]
    ref: str
    issued_at: datetime | None = None
    quote: str | None = Field(default=None, description="Verbatim span the claim rests on")


class Claim(BaseModel):
    """One assertion in a briefing. Cannot exist without at least one citation."""

    model_config = ConfigDict(frozen=True)

    text: str
    citations: tuple[Citation, ...] = Field(min_length=1)
    verified: bool | None = Field(
        default=None, description="Set by the NLI verifier; None means not yet checked"
    )
    entailment_score: float | None = Field(default=None, ge=0.0, le=1.0)


class Finding(BaseModel):
    """A ranked hazard in the briefing."""

    model_config = ConfigDict(frozen=True)

    category: str
    severity: Severity
    phases: tuple[Phase, ...] = ()
    headline: str
    claims: tuple[Claim, ...] = Field(min_length=1)
    airport: str | None = Field(default=None, description="ICAO this finding is about")

    @property
    def sort_key(self) -> tuple[int, int]:
        return (-self.severity.rank, -len(self.claims))


class Abstention(BaseModel):
    """Something the system deliberately declined to answer.

    A first-class output, not an error path. Evaluated directly.
    """

    model_config = ConfigDict(frozen=True)

    topic: str
    reason: Literal["stale_source", "no_coverage", "conflicting_sources", "parse_failure"]
    detail: str


class FlightRequest(BaseModel):
    departure: ICAO
    destination: ICAO
    alternates: tuple[ICAO, ...] = ()
    off_block: datetime
    aircraft_type: str | None = None
    route: str | None = None
    ete_minutes: int | None = Field(default=None, ge=1, description="Estimated time en route")


class Briefing(BaseModel):
    """The system's output."""

    request: FlightRequest
    generated_at: datetime
    findings: tuple[Finding, ...] = ()
    abstentions: tuple[Abstention, ...] = ()

    sources_considered: int = 0
    trace_id: str | None = None
    cost_usd: float | None = None
    latency_ms: int | None = None

    def ranked(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: f.sort_key)

    @property
    def grounded(self) -> bool:
        """True when every checked claim passed the verifier."""
        return all(c.verified is not False for f in self.findings for c in f.claims)
