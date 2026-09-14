"""Persistence for decoded NOTAMs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from psycopg import Connection

from preflight.schemas import Entity, EntityState, EntityType, NotamRecord, Phase, Severity

_UPSERT = """
INSERT INTO notams (
    id, icao, fir, kind, replaces,
    effective_from, effective_to, permanent, estimated_end,
    qcode, qcode_text, traffic, purpose, scope, lower_fl, upper_fl, radius_nm, schedule,
    raw, body, body_expanded,
    hazard_class, severity, phases,
    decoder, decode_confidence, fetched_at
) VALUES (
    %(id)s, %(icao)s, %(fir)s, %(kind)s, %(replaces)s,
    %(effective_from)s, %(effective_to)s, %(permanent)s, %(estimated_end)s,
    %(qcode)s, %(qcode_text)s, %(traffic)s, %(purpose)s, %(scope)s,
    %(lower_fl)s, %(upper_fl)s, %(radius_nm)s, %(schedule)s,
    %(raw)s, %(body)s, %(body_expanded)s,
    %(hazard_class)s, %(severity)s, %(phases)s,
    %(decoder)s, %(decode_confidence)s, now()
)
ON CONFLICT (id) DO UPDATE SET
    icao = EXCLUDED.icao, fir = EXCLUDED.fir, kind = EXCLUDED.kind,
    replaces = EXCLUDED.replaces,
    effective_from = EXCLUDED.effective_from, effective_to = EXCLUDED.effective_to,
    permanent = EXCLUDED.permanent, estimated_end = EXCLUDED.estimated_end,
    qcode = EXCLUDED.qcode, qcode_text = EXCLUDED.qcode_text,
    traffic = EXCLUDED.traffic, purpose = EXCLUDED.purpose, scope = EXCLUDED.scope,
    lower_fl = EXCLUDED.lower_fl, upper_fl = EXCLUDED.upper_fl, radius_nm = EXCLUDED.radius_nm,
    schedule = EXCLUDED.schedule,
    raw = EXCLUDED.raw, body = EXCLUDED.body, body_expanded = EXCLUDED.body_expanded,
    hazard_class = EXCLUDED.hazard_class, severity = EXCLUDED.severity,
    phases = EXCLUDED.phases,
    decoder = EXCLUDED.decoder, decode_confidence = EXCLUDED.decode_confidence,
    fetched_at = now()
"""

_INSERT_ENTITY = """
INSERT INTO notam_entities (notam_id, type, ref, state, cause, detail, span_start, span_end)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
"""

_COLUMNS = (
    "id, icao, fir, kind, replaces, effective_from, effective_to, permanent, estimated_end, "
    "qcode, qcode_text, traffic, purpose, scope, lower_fl, upper_fl, radius_nm, schedule, "
    "raw, body, body_expanded, "
    "hazard_class, severity, phases, decoder, decode_confidence"
)

# "Everything in force at this airport at this instant." Missing bounds are
# open, permanent NOTAMs never expire — same semantics as NotamRecord.active_at.
_ACTIVE = f"""
SELECT {_COLUMNS} FROM notams
WHERE icao = %(icao)s
  AND (effective_from IS NULL OR effective_from <= %(at)s)
  AND (permanent OR effective_to IS NULL OR effective_to >= %(at)s)
ORDER BY
  CASE severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 WHEN 'LOW' THEN 2 ELSE 3 END,
  effective_from DESC NULLS LAST
"""

# NOTAMs whose validity overlaps [start, end] — what a flight in that window sees.
_DURING = f"""
SELECT {_COLUMNS} FROM notams
WHERE icao = %(icao)s
  AND (effective_from IS NULL OR effective_from <= %(end)s)
  AND (permanent OR effective_to IS NULL OR effective_to >= %(start)s)
ORDER BY
  CASE severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 WHEN 'LOW' THEN 2 ELSE 3 END,
  effective_from DESC NULLS LAST
"""

_ENTITIES_FOR = """
SELECT notam_id, type, ref, state, cause, detail, span_start, span_end
FROM notam_entities WHERE notam_id = ANY(%s) ORDER BY id
"""

_LOW_CONFIDENCE = f"""
SELECT {_COLUMNS} FROM notams
WHERE decode_confidence < %(threshold)s
ORDER BY decode_confidence ASC, fetched_at DESC
LIMIT %(limit)s
"""


def upsert(conn: Connection[Any], rec: NotamRecord) -> None:
    """Insert or refresh one NOTAM and replace its entity rows."""
    params = rec.model_dump(
        include={
            "id", "icao", "fir", "kind", "replaces", "effective_from", "effective_to",
            "permanent", "estimated_end", "qcode", "qcode_text", "traffic", "purpose", "scope",
            "lower_fl", "upper_fl", "radius_nm", "schedule", "raw", "body", "body_expanded",
            "hazard_class",
            "decoder", "decode_confidence",
        }
    )
    params["severity"] = rec.severity.value
    params["phases"] = [p.value for p in rec.phases]
    conn.execute(_UPSERT, params)
    conn.execute("DELETE FROM notam_entities WHERE notam_id = %s", (rec.id,))
    for e in rec.entities:
        start, end = e.span if e.span else (None, None)
        conn.execute(
            _INSERT_ENTITY,
            (rec.id, e.type.value, e.ref, e.state.value, e.cause, e.detail, start, end),
        )


def upsert_many(conn: Connection[Any], records: list[NotamRecord]) -> int:
    for rec in records:
        upsert(conn, rec)
    return len(records)


def active_at(conn: Connection[Any], icao: str, at: datetime) -> list[NotamRecord]:
    rows = conn.execute(_ACTIVE, {"icao": icao, "at": at}).fetchall()
    return _hydrate(conn, rows)


def active_during(
    conn: Connection[Any], icao: str, start: datetime, end: datetime
) -> list[NotamRecord]:
    rows = conn.execute(_DURING, {"icao": icao, "start": start, "end": end}).fetchall()
    return _hydrate(conn, rows)


def count_for(conn: Connection[Any], icao: str) -> int:
    """NOTAMs ever stored for the airport, active or not — zero means the archive has no
    coverage there, which is a different fact from "nothing in force"."""
    row = conn.execute("SELECT count(*) FROM notams WHERE icao = %s", (icao,)).fetchone()
    return int(row[0]) if row else 0


def low_confidence(conn: Connection[Any], threshold: float, limit: int = 100) -> list[NotamRecord]:
    """The escalation queue: parses the rule layer did not trust."""
    rows = conn.execute(_LOW_CONFIDENCE, {"threshold": threshold, "limit": limit}).fetchall()
    return _hydrate(conn, rows)


def _hydrate(conn: Connection[Any], rows: list[tuple[Any, ...]]) -> list[NotamRecord]:
    if not rows:
        return []
    ids = [r[0] for r in rows]
    by_notam: dict[str, list[Entity]] = {i: [] for i in ids}
    for nid, etype, ref, state, cause, detail, s, e in conn.execute(_ENTITIES_FOR, (ids,)):
        by_notam[nid].append(Entity(
            type=EntityType(etype), ref=ref, state=EntityState(state),
            cause=cause, detail=detail,
            span=(s, e) if s is not None and e is not None else None,
        ))
    return [_row_to_record(r, tuple(by_notam[r[0]])) for r in rows]


def _row_to_record(row: tuple[Any, ...], entities: tuple[Entity, ...]) -> NotamRecord:
    (
        id_, icao, fir, kind, replaces, eff_from, eff_to, permanent, estimated_end,
        qcode, qcode_text, traffic, purpose, scope, lower_fl, upper_fl, radius_nm, schedule,
        raw, body, body_expanded, hazard_class, severity, phases, decoder, decode_confidence,
    ) = row
    return NotamRecord(
        id=id_, icao=icao, fir=fir, kind=kind, replaces=replaces,
        effective_from=eff_from, effective_to=eff_to,
        permanent=permanent, estimated_end=estimated_end,
        qcode=qcode, qcode_text=qcode_text, traffic=traffic, purpose=purpose, scope=scope,
        lower_fl=lower_fl, upper_fl=upper_fl, radius_nm=radius_nm, schedule=schedule,
        raw=raw, body=body, body_expanded=body_expanded,
        entities=entities,
        hazard_class=hazard_class, severity=Severity(severity),
        phases=tuple(Phase(p) for p in phases),
        decoder=decoder, decode_confidence=decode_confidence,
    )
