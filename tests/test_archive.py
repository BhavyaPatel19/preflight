from datetime import UTC, datetime, timedelta

import pytest

from preflight.archive import archive_raw, snapshots

T = datetime(2026, 9, 11, 14, 30, 5, 123456, tzinfo=UTC)


def test_layout_is_kind_date_time_source(tmp_path):
    p = archive_raw("notams", "nasa-dip", "RAW", fetched_at=T, root=tmp_path)
    assert p == tmp_path / "notams" / "2026-09-11" / "143005.123456Z-nasa-dip.txt"
    assert p.read_text() == "RAW"


def test_extension_follows_kind(tmp_path):
    assert archive_raw("metar", "s", "[]", fetched_at=T, root=tmp_path).suffix == ".json"
    assert archive_raw("taf", "s", "[]", fetched_at=T, root=tmp_path).suffix == ".json"
    assert archive_raw("other", "s", "x", fetched_at=T, root=tmp_path).suffix == ".txt"


def test_same_second_different_microsecond_does_not_collide(tmp_path):
    a = archive_raw("notams", "s", "1", fetched_at=T, root=tmp_path)
    b = archive_raw("notams", "s", "2", fetched_at=T + timedelta(microseconds=1), root=tmp_path)
    assert a != b and a.read_text() == "1" and b.read_text() == "2"


def test_source_name_is_sanitised_for_filesystem(tmp_path):
    p = archive_raw("notams", "file:/etc/passwd", "x", fetched_at=T, root=tmp_path)
    assert p.parent == tmp_path / "notams" / "2026-09-11"
    assert "/" not in p.name[len("143005.123456Z-"):]


def test_non_utc_timestamps_are_normalised(tmp_path):
    from datetime import timezone

    est = T.astimezone(timezone(timedelta(hours=-5)))
    p = archive_raw("notams", "s", "x", fetched_at=est, root=tmp_path)
    assert "143005.123456Z" in p.name


def test_naive_timestamp_rejected(tmp_path):
    with pytest.raises(ValueError):
        archive_raw("notams", "s", "x", fetched_at=T.replace(tzinfo=None), root=tmp_path)


def test_snapshots_oldest_first_and_empty_when_missing(tmp_path):
    assert snapshots("notams", root=tmp_path) == []
    later = archive_raw("notams", "s", "b", fetched_at=T + timedelta(days=1), root=tmp_path)
    earlier = archive_raw("notams", "s", "a", fetched_at=T, root=tmp_path)
    assert snapshots("notams", root=tmp_path) == [earlier, later]
