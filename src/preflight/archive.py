"""Raw-payload archive.

Every fetch is written to disk before it is decoded, keyed by the instant it was
fetched. This is the foundation of the time-travel evaluation: nobody hands out
historical NOTAMs, so from today we keep our own. Local filesystem now; the
MinIO bucket in compose is the same layout with a different root.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from preflight.config import settings

_EXT = {"notams": "txt", "metar": "json", "taf": "json"}


def archive_raw(
    kind: str,
    source: str,
    payload: str,
    *,
    fetched_at: datetime | None = None,
    root: Path | None = None,
) -> Path:
    """Write ``payload`` under ``<root>/<kind>/<YYYY-MM-DD>/<HHMMSS.ffffff>Z-<source>.<ext>``.

    Microsecond timestamps keep two fetches in the same second from colliding;
    the source name in the filename keeps two providers' snapshots distinguishable.
    """
    at = fetched_at or datetime.now(UTC)
    if at.tzinfo is None:
        raise ValueError("fetched_at must be timezone-aware")
    at = at.astimezone(UTC)
    safe_source = "".join(c if c.isalnum() or c in "-_." else "_" for c in source)
    ext = _EXT.get(kind, "txt")

    directory = (root or settings().archive_dir) / kind / at.strftime("%Y-%m-%d")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{at.strftime('%H%M%S.%f')}Z-{safe_source}.{ext}"
    path.write_text(payload)
    return path


def snapshots(kind: str, *, root: Path | None = None) -> list[Path]:
    """All archived files of ``kind``, oldest first."""
    base = (root or settings().archive_dir) / kind
    if not base.exists():
        return []
    return sorted(p for p in base.rglob("*") if p.is_file())
