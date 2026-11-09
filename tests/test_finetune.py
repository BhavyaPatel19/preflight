"""Embedder fine-tuning data: synopsis→narrative pairs, with every eval report held out."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from preflight.retrieval import finetune as FT
from preflight.retrieval.embed import query_prefix

SYN = "The flight crew of an A320 reported a runway incursion at night after a confusing hold."


def test_pair_takes_the_synopsis_and_the_first_narrative_chunk() -> None:
    chunks = ["We were cleared to taxi via B and crossed 28L in error.",
              "Second part of the narrative.\n\nSynopsis: " + SYN]
    p = FT.pair_from_chunks("1234567", chunks)
    assert p == FT.Pair("1234567", SYN, chunks[0])


@pytest.mark.parametrize("chunks", [
    ["Only a narrative, no synopsis."],
    ["Synopsis: " + SYN],                               # synopsis-only: no passage to learn
    ["Narrative.\n\nSynopsis: too short"],
])
def test_reports_without_a_usable_pair_are_skipped(chunks: list[str]) -> None:
    assert FT.pair_from_chunks("1", chunks) is None


def test_held_out_ids_cover_retrieval_targets_and_precedent_hits(tmp_path: Path) -> None:
    golden = tmp_path / "golden.jsonl"
    golden.write_text(json.dumps({"kind": "synopsis", "relevant": ["111"]}) + "\n"
                      + json.dumps({"kind": "identifier", "relevant": []}) + "\n")
    pairs = tmp_path / "pairs.jsonl"
    pairs.write_text(json.dumps({"hit_ref": "asrs:222"}) + "\n"
                     + json.dumps({"hit_ref": "ntsb:ABC"}) + "\n")
    assert FT.held_out_ids(golden, pairs) == {"111", "222"}


def test_the_committed_eval_sets_are_held_out() -> None:
    held = FT.held_out_ids()
    targets = {r for line in FT.RETRIEVAL_GOLDEN.read_text().splitlines() if line.strip()
               for r in json.loads(line)["relevant"]}
    assert targets and targets <= held


def test_finetuned_model_keeps_its_query_prefix(tmp_path: Path) -> None:
    (tmp_path / "preflight_finetune.json").write_text(json.dumps({"query_prefix": "Q: "}))
    assert query_prefix(str(tmp_path)) == "Q: "
    assert query_prefix("BAAI/bge-large-en-v1.5").startswith("Represent this sentence")
    assert query_prefix("BAAI/bge-m3") == ""


@pytest.mark.db
def test_build_pairs_never_reads_a_held_out_report(db) -> None:
    def add(ext: str, *texts: str) -> None:
        doc = db.execute("INSERT INTO documents (source, external_id) VALUES ('asrs', %s) "
                         "RETURNING id", (ext,)).fetchone()
        assert doc is not None
        for i, t in enumerate(texts):
            db.execute("INSERT INTO chunks (document_id, ordinal, text) VALUES (%s, %s, %s)",
                       (doc[0], i, t))

    add("ft-1", "Narrative one.", "Synopsis: " + SYN)
    add("ft-2", "Narrative two.", "Synopsis: " + SYN)
    add("ft-3", "Narrative three, no synopsis.")
    got = FT.build_pairs(db, exclude={"ft-2"}, limit=10)
    reports = {p.report for p in got}
    assert "ft-1" in reports and "ft-2" not in reports and "ft-3" not in reports
