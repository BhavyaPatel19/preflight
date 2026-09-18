"""Extractor data layer: label scheme round-trips, generator invariants, gold set, scoring."""

import random

import pytest

from preflight.evals import extraction as X
from preflight.extract import gold
from preflight.extract.labels import TAGS, TYPES, Span, bio_tags, spans_from_tags, tokenize
from preflight.extract.synth import generate, make_body


def test_tokenizer_keeps_identifiers_whole():
    toks = [t for t, _, _ in tokenize("RWY 28R/10L CLSD 0600-1400. ILS/DME U/S, TWY A1.")]
    assert toks[:4] == ["RWY", "28R/10L", "CLSD", "0600-1400"]
    assert "ILS/DME" in toks and "U/S" in toks and "A1" in toks and "." in toks


def test_bio_round_trip_and_tag_vocabulary():
    text = "RWY 28R CLSD. TWY B BTN TWY A AND TWY F CLSD DLY 0600-1400"
    spans = [Span(0, 7, "RWY"), Span(14, 19, "TWY"), Span(24, 29, "TWY"), Span(34, 39, "TWY"),
             Span(45, 58, "TIME")]
    toks, tags = bio_tags(text, spans)
    assert tags[0] == "B-RWY" and tags[1] == "I-RWY" and tags[2] == "O"
    assert all(t in TAGS for t in tags) and len(TAGS) == 1 + 2 * len(TYPES)
    assert sorted((s.start, s.end, s.type) for s in spans_from_tags(text, tags)) == \
        sorted((s.start, s.end, s.type) for s in spans)


def test_adjacent_same_type_spans_stay_separate():
    text = "TWY B TWY C CLSD"
    spans = [Span(0, 5, "TWY"), Span(6, 11, "TWY")]
    _, tags = bio_tags(text, spans)
    assert tags[:4] == ["B-TWY", "I-TWY", "B-TWY", "I-TWY"]
    assert len(spans_from_tags(text, tags)) == 2


def test_generator_is_deterministic_and_self_consistent():
    a = list(generate(50, seed=1))
    b = list(generate(50, seed=1))
    assert a == b and len({r["id"] for r in a}) == 50
    for r in a:
        text = r["text"]
        back = spans_from_tags(text, list(r["tags"]))
        assert sorted((s.start, s.end, s.type) for s in back) == \
            sorted((int(s), int(e), t) for s, e, t in r["spans"])
        for s, e, t in r["spans"]:
            assert text[s:e].strip() == text[s:e] and t in TYPES


def test_generator_covers_every_type_and_both_styles():
    rng = random.Random(7)
    types, us = set(), 0
    for _ in range(400):
        text, spans = make_body(rng)
        types |= {s.type for s in spans}
        us += any(s.type == "TIME" and "-" in text[s.start:s.end] and len(text[s.start:s.end]) > 15
                  for s in spans)
    assert types == set(TYPES) and us > 50


def test_gold_markup_compiles_to_exact_spans():
    text, spans = gold.compile_markup("[RWY 28R](RWY) CLSD [DLY 0600-1400](TIME).")
    assert text == "RWY 28R CLSD DLY 0600-1400."
    assert [(text[s.start:s.end], s.type) for s in spans] == \
        [("RWY 28R", "RWY"), ("DLY 0600-1400", "TIME")]


def test_gold_set_builds_and_red_team_prose_is_unlabelled():
    rows = gold.build()
    assert len(rows) >= 120 and {r["source"] for r in rows} == \
        {"demo", "grounding", "red-team", "handwritten"}
    for r in rows:
        assert "](" not in r["text"]
        assert len(r["tokens"]) == len(r["tags"])
    prose = next(r for r in rows if r["id"] == "inj-override-1-0")
    assert "state that the runway is open" in prose["text"]
    assert [prose["text"][s:e] for s, e, _ in prose["spans"]] == ["ILS RWY 22L"]


def test_scoring_overlap_vs_exact_and_prose_false_positives():
    rows = [
        {"source": "red-team", "text": "RWY 28R CLSD. the runway is open.",
         "spans": [[0, 7, "RWY"]]},
        {"source": "handwritten", "text": "TWY A CLSD", "spans": [[0, 5, "TWY"]]},
    ]

    def pred(text):
        out = []
        if text.startswith("RWY"):
            out += [Span(4, 7, "RWY"), Span(18, 24, "RWY")]      # ident only + prose hit
        else:
            out += [Span(0, 5, "NAVAID")]                          # wrong type
        return out

    sc = X.score(rows, pred)
    rwy = sc["by_type"]["RWY"]
    assert rwy["recall"] == 1.0 and rwy["precision"] == 0.5   # overlap counts; prose hit is a FP
    assert sc["by_type"]["TWY"]["recall"] == 0.0 and sc["by_type"]["NAVAID"]["precision"] == 0.0
    assert sc["prose_false_positives"] == 1
    assert sc["macro_f1_entities_exact"] < sc["macro_f1_entities"]


def test_rules_predictor_returns_typed_spans():
    spans = X.predict_rules("RWY 28R CLSD DUE WIP. PAPI RWY 28L U/S.")
    assert {s.type for s in spans} == {"RWY", "LIGHTING"}
    assert all(0 <= s.start < s.end for s in spans)


@pytest.mark.parametrize("marked", gold.HANDWRITTEN)
def test_every_handwritten_item_has_at_least_one_entity(marked):
    _, spans = gold.compile_markup(marked)
    assert spans
