from preflight.retrieval.chunk import chunk_text, sentences


def test_sentences_split_on_terminators_and_collapse_whitespace():
    assert sentences("One.  Two!\n\nThree? 4th.") == ["One.", "Two!", "Three?", "4th."]


def test_sentences_do_not_split_inside_decimals_or_abbreviated_ids():
    # "300 ft." ends a sentence; "0.5 SM" does not.
    assert sentences("Visibility 0.5 SM at 300 ft. Go-around.") == [
        "Visibility 0.5 SM at 300 ft.", "Go-around."
    ]


def test_empty_text_yields_no_chunks():
    assert chunk_text("") == [] and chunk_text("   \n ") == []


def test_short_text_is_one_chunk():
    cs = chunk_text("A short note. Two sentences.")
    assert len(cs) == 1 and cs[0].ordinal == 0 and cs[0].text == "A short note. Two sentences."


def test_chunks_are_sentence_aligned_and_near_target():
    text = " ".join(f"Sentence number {i} says something about runway {i % 3}." for i in range(60))
    cs = chunk_text(text, target=400)
    assert len(cs) > 3
    assert [c.ordinal for c in cs] == list(range(len(cs)))
    for c in cs:
        assert c.text.endswith(".")            # never cut mid-sentence
        assert len(c.text) <= 400 + 60         # one sentence of slack at most


def test_overlap_carries_last_sentence_forward():
    text = " ".join(f"S{i} ends here." for i in range(40))
    cs = chunk_text(text, target=120, overlap=True)
    for a, b in zip(cs, cs[1:], strict=False):
        last = a.text.split(". ")[-1].rstrip(".")
        assert b.text.startswith(last)


def test_no_overlap_when_disabled():
    text = " ".join(f"S{i} ends here." for i in range(40))
    cs = chunk_text(text, target=120, overlap=False)
    joined = " ".join(c.text for c in cs)
    assert joined == text                       # partition, no duplication


def test_oversize_sentence_is_not_glued_to_what_follows():
    big = "x" * 900 + "."
    cs = chunk_text(f"Small. {big} Small again.", target=300)
    holders = [c for c in cs if big in c.text]
    assert len(holders) == 1                    # appears exactly once
    assert "Small again" not in holders[0].text  # the next sentence starts a new chunk
    assert cs[-1].text == "Small again."
