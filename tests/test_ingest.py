"""Pure parts of the ingestion jobs — no database, no network."""

from preflight.decode.notam import DEMO_NOTAMS
from preflight.ingest.notams import decode_many, split_dump


def test_split_dump_on_blank_lines():
    text = "\n\n".join(DEMO_NOTAMS) + "\n\n\n"
    assert split_dump(text) == [n.strip() for n in DEMO_NOTAMS]


def test_split_dump_keeps_multiline_icao_notams_together():
    chunks = split_dump(DEMO_NOTAMS[0])
    assert len(chunks) == 1 and "E)" in chunks[0]


def test_decode_many_separates_failures_from_successes():
    ok, failed = decode_many(DEMO_NOTAMS + ["this is not a notam"])
    assert len(ok) == 3 and failed == ["this is not a notam"]
