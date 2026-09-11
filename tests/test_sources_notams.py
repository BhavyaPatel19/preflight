from datetime import UTC, datetime

import pytest

from preflight.decode.notam import DEMO_NOTAMS
from preflight.sources.notams import (
    FileSource,
    NasaDipSource,
    NotamSource,
    RawNotam,
    SourceUnavailable,
    split_dump,
)


def test_split_dump_on_blank_lines():
    text = "\n\n".join(DEMO_NOTAMS) + "\n\n\n"
    assert split_dump(text) == [n.strip() for n in DEMO_NOTAMS]


def test_split_dump_keeps_multiline_icao_notams_together():
    chunks = split_dump(DEMO_NOTAMS[0])
    assert len(chunks) == 1 and "E)" in chunks[0]


async def test_file_source_reads_and_tags(tmp_path):
    dump = tmp_path / "kzzy.txt"
    dump.write_text("\n\n".join(DEMO_NOTAMS))
    src = FileSource(dump)
    raws = await src.fetch()
    assert len(raws) == 3
    assert all(isinstance(r, RawNotam) for r in raws)
    assert raws[0].source == "file:kzzy.txt"
    assert raws[0].fetched_at.tzinfo is UTC
    assert raws[0].text.startswith("A1477/26")


async def test_file_source_concatenates_multiple_files(tmp_path):
    a, b = tmp_path / "a.txt", tmp_path / "b.txt"
    a.write_text(DEMO_NOTAMS[0])
    b.write_text("\n\n".join(DEMO_NOTAMS[1:]))
    raws = await FileSource(a, b).fetch()
    assert [r.source for r in raws] == ["file:a.txt", "file:b.txt", "file:b.txt"]


def test_file_source_requires_a_path():
    with pytest.raises(ValueError):
        FileSource()


def test_sources_satisfy_the_protocol(tmp_path):
    assert isinstance(FileSource(tmp_path / "x"), NotamSource)
    assert isinstance(NasaDipSource(None, None), NotamSource)


async def test_nasa_dip_unconfigured_fails_loudly():
    with pytest.raises(SourceUnavailable, match="not configured"):
        await NasaDipSource(None, None).fetch(["KSFO"])


async def test_nasa_dip_configured_but_unwired_still_refuses_to_guess():
    src = NasaDipSource("https://example.invalid", "token")
    with pytest.raises(SourceUnavailable, match="observed response"):
        await src.fetch(["KSFO"])
    await src.aclose()


def test_raw_notam_is_immutable():
    from pydantic import ValidationError

    r = RawNotam(text="x", source="s", fetched_at=datetime.now(UTC))
    with pytest.raises(ValidationError):
        r.text = "y"  # type: ignore[misc]
