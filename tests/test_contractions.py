from preflight.decode.contractions import CONTRACTIONS, coverage, expand


def test_expands_common_notam_terms():
    assert expand("RWY 28R CLSD") == "runway 28R closed"


def test_multichar_token_wins_over_prefix():
    # "U/S" must not be mangled by a shorter match.
    assert expand("PAPI U/S") == "precision approach path indicator unserviceable"


def test_keep_original_annotates_rather_than_replaces():
    out = expand("RWY CLSD", keep_original=True)
    assert "RWY (runway)" in out and "CLSD (closed)" in out


def test_word_boundaries_respected():
    # A contraction embedded in a longer token must be left alone.
    assert expand("SNOWBIRD") == "SNOWBIRD"
    assert expand("SN") == "snow"


def test_coverage_scores_telegraphic_higher_than_prose():
    assert coverage("RWY CLSD WIP TWY") > coverage("the quick brown fox jumped")


def test_coverage_of_empty_is_zero():
    assert coverage("") == 0.0 and coverage("   ") == 0.0


def test_dictionary_is_upper_case_and_populated():
    assert len(CONTRACTIONS) > 250
    assert all(k == k.upper() for k in CONTRACTIONS)
