"""Abstention eval: the case set is well-formed, and the current rules pass it."""

import pytest

from preflight.evals import abstention as AB


def test_case_set_is_well_formed():
    cs = AB.cases()
    assert len({c.id for c in cs}) == len(cs)
    for c in cs:
        if c.gap in {"none", "notams_inactive"}:
            assert c.expect == ()
        else:
            assert c.expect and all(topic and reason for topic, reason in c.expect)
    everything = next(c for c in cs if c.gap == "everything")
    assert len(everything.expect) == 6 and ("precedent", "no_coverage") in everything.expect
    # departure never carries a forecast or delay gap: those are arrival-side sources
    assert not any(c.gap in {"taf_missing", "delay_none"} for c in cs if c.role == "departure")


def test_markdown_lists_misses_and_spurious():
    res = {"ran_at": "t", "git_sha": "abc", "cases": 2, "gap_cases": 1, "recall": 0.0,
           "false_abstention_rate": 0.5,
           "by_gap": {"none": {"cases": 1, "hits": 1, "spurious": 1}},
           "misses": [{"case": "x:y", "expected": [("a", "b")], "got": []}],
           "spurious": [{"case": "d:none", "unexpected": [("a", "b")]}],
           "reasons_never_emitted": ["conflicting_sources"]}
    md = AB.to_markdown(res)
    assert "**Misses**" in md and "`x:y`" in md and "**Spurious**" in md
    assert "`conflicting_sources`" in md


@pytest.mark.db
def test_current_rules_pass_every_constructed_case(db):
    res = AB.run(db)
    assert res["recall"] == 1.0 and res["false_abstention_rate"] == 0.0, res
    assert res["cases"] == 26 and res["gap_cases"] == 20
    # Rolled back: the synthetic airports leave nothing behind.
    assert db.execute("SELECT count(*) FROM notams WHERE icao LIKE 'KZZ%'").fetchone()[0] == 0
