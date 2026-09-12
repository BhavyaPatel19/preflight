from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import structlog

from preflight.archive import archive_raw
from preflight.db import get_pool
from preflight.db import notams as ndb
from preflight.decode.notam import NotamParseError, parse_notam
from preflight.safety.injection import detect
from preflight.schemas import NotamRecord
from preflight.sources.notams import NotamSource

log = structlog.get_logger(__name__)


def decode_many(raws: Sequence[str]) -> tuple[list[NotamRecord], list[str]]:
    """Decode what parses; return the rest so nothing is silently dropped."""
    records: list[NotamRecord] = []
    failed: list[str] = []
    for raw in raws:
        try:
            records.append(parse_notam(raw))
        except NotamParseError:
            failed.append(raw)
    return records, failed


async def ingest_notams(source: NotamSource, icaos: Sequence[str] = ()) -> dict[str, int | str]:
    """Fetch from ``source``, archive the raw batch, decode, store.

    Archive happens before decode on purpose: a parser bug must never cost us
    the snapshot. The archive is what the time-travel evaluation replays.
    """
    raws = await source.fetch(icaos)
    fetched_at = raws[0].fetched_at if raws else datetime.now(UTC)
    archived = archive_raw(
        "notams", source.name, "\n\n".join(r.text for r in raws), fetched_at=fetched_at
    )

    records, failed = decode_many([r.text for r in raws])
    verdicts = {r.id: detect(r.body) for r in records}
    flagged = [rid for rid, v in verdicts.items() if v.suspicious]
    with get_pool().connection() as conn:
        stored = ndb.upsert_many(conn, records)
        for rid, v in verdicts.items():
            conn.execute("UPDATE notams SET injection_score = %s WHERE id = %s", (v.score, rid))
        conn.commit()

    low = sum(1 for r in records if r.decode_confidence < 0.6)
    if flagged:
        log.warning("notams.suspicious", ids=flagged,
                    signals={rid: list(verdicts[rid].signals) for rid in flagged})
    log.info(
        "notams.ingested", source=source.name, fetched=len(raws), stored=stored,
        unparseable=len(failed), low_confidence=low, suspicious=len(flagged),
        archive=str(archived),
    )
    return {
        "fetched": len(raws), "stored": stored, "unparseable": len(failed),
        "low_confidence": low, "suspicious": len(flagged), "archive": str(archived),
    }
