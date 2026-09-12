"""NOTAM sources behind one interface.

Programmatic access to US NOTAMs is not open to the public in 2026 — see
docs/adr/0002. So the ingestion pipeline is written against a small protocol,
and each provider is a plug: a text dump today, NASA's public redistribution of
the FAA feed once access is granted, others if they appear. Nothing above this
module knows or cares which one is in use.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict


class RawNotam(BaseModel):
    """One NOTAM as received, before decoding. ``text`` is what gets archived and cited."""

    model_config = ConfigDict(frozen=True)

    text: str
    source: str
    fetched_at: datetime
    external_id: str | None = None


class SourceUnavailable(RuntimeError):
    """The provider cannot serve right now (no credentials, access pending, upstream down)."""


@runtime_checkable
class NotamSource(Protocol):
    name: str

    async def fetch(self, icaos: Sequence[str]) -> list[RawNotam]: ...


# NOTAMs in a text dump are separated by blank lines; ICAO ones may span lines.
_SPLIT = re.compile(r"\n\s*\n")


def split_dump(text: str) -> list[str]:
    return [chunk.strip() for chunk in _SPLIT.split(text) if chunk.strip()]


class FileSource:
    """A text dump: manual exports, fixtures, or a re-read of our own archive.

    Ignores ``icaos`` — a dump is whatever it is. Filtering happens after decode,
    where the airport is a parsed field rather than a guess.
    """

    name = "file"

    def __init__(self, *paths: Path):
        if not paths:
            raise ValueError("FileSource needs at least one path")
        self.paths = tuple(Path(p) for p in paths)

    async def fetch(self, icaos: Sequence[str] = ()) -> list[RawNotam]:
        now = datetime.now(UTC)
        out: list[RawNotam] = []
        for path in self.paths:
            out.extend(
                RawNotam(text=chunk, source=f"file:{path.name}", fetched_at=now)
                for chunk in split_dump(path.read_text())
            )
        return out


class NasaDipSource:
    """NASA Digital Information Platform — public redistribution of the FAA SWIM feed.

    Access is by request (submitted 2026-09-11). The request/response shape is
    deliberately NOT implemented from documentation: it gets written against
    an observed response, the same way the aviationweather client was, once a
    token exists. Until then this fails loudly rather than pretending.
    """

    name = "nasa-dip"

    def __init__(
        self,
        base_url: str | None,
        token: str | None,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/") if base_url else None
        self.token = token
        self._client = client or httpx.AsyncClient(timeout=20.0)

    async def fetch(self, icaos: Sequence[str]) -> list[RawNotam]:
        if not (self.base_url and self.token):
            raise SourceUnavailable(
                "NASA DIP is not configured (PREFLIGHT_NASA_DIP_BASE_URL / _TOKEN). "
                "Access was requested 2026-09-11 — see docs/adr/0002."
            )
        raise SourceUnavailable(
            "NASA DIP client is not wired yet: the endpoint shape will be implemented "
            "from an observed response once access is granted, not guessed."
        )

    async def aclose(self) -> None:
        await self._client.aclose()
