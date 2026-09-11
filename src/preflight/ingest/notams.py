from __future__ import annotations

import re
from pathlib import Path

import structlog

from preflight.db import get_pool
from preflight.db import notams as ndb
from preflight.decode.notam import NotamParseError, parse_notam
from preflight.schemas import NotamRecord

log = structlog.get_logger(__name__)

# NOTAMs in a text dump are separated by blank lines; ICAO ones may span lines.
_SPLIT = re.compile(r"\n\s*\n")


def split_dump(text: str) -> list[str]:
    return [chunk.strip() for chunk in _SPLIT.split(text) if chunk.strip()]


def decode_many(raws: list[str]) -> tuple[list[NotamRecord], list[str]]:
    """Decode what parses; return the rest so nothing is silently dropped."""
    records: list[NotamRecord] = []
    failed: list[str] = []
    for raw in raws:
        try:
            records.append(parse_notam(raw))
        except NotamParseError:
            failed.append(raw)
    return records, failed


def ingest_notams(raws: list[str]) -> dict[str, int]:
    """Decode and store a batch of raw NOTAMs.

    The source is a list of strings so the same job serves a text dump today
    and the FAA API client once its key is in place.
    """
    records, failed = decode_many(raws)
    with get_pool().connection() as conn:
        stored = ndb.upsert_many(conn, records)
        conn.commit()
    low = sum(1 for r in records if r.decode_confidence < 0.6)
    log.info("notams.ingested", stored=stored, unparseable=len(failed), low_confidence=low)
    return {"stored": stored, "unparseable": len(failed), "low_confidence": low}


def ingest_file(path: Path) -> dict[str, int]:
    return ingest_notams(split_dump(path.read_text()))
