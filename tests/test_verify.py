"""Grounding verifier: premise construction, annotation policy, and the corruption generator."""

from datetime import UTC, datetime

from preflight.brief.core import notam_findings
from preflight.decode.notam import DEMO_NOTAMS, parse_notam
from preflight.evals.grounding import corrupt
from preflight.schemas import Briefing, Citation, FlightRequest
from preflight.verify.ground import premise_for, summary, unverified, with_verification

T0 = datetime(2026, 9, 11, 2, 30, tzinfo=UTC)


def _briefing():
    f = notam_findings("KSFO", "departure", [parse_notam(DEMO_NOTAMS[0])])
    return Briefing(request=FlightRequest(departure="KSFO", destination="KJFK", off_block=T0),
                    generated_at=T0, findings=tuple(f))


class FakeVerifier:
    name = "fake"

    def __init__(self, score_for):
        self.score_for = score_for
        self.pairs = []

    def entailment(self, pairs):
        self.pairs.extend(pairs)
        return [self.score_for(p, h) for p, h in pairs]


# ---------------------------------------------------------------- premise

def test_premise_expands_notam_contractions_and_prefixes_airport():
    cit = Citation(kind="notam", ref="x", quote="RWY 28R CLSD DUE WIP. PAPI RWY 28L U/S.")
    p = premise_for(cit, "KSFO")
    assert p.startswith("NOTAM x at KSFO states: runway 28R closed due to work in progress.")
    assert "precision approach path indicator runway 28L unserviceable" in p
    assert "CLSD" not in p and "U/S" not in p
    assert "unserviceable means not working" in p          # glossary for the NLI model


def test_premise_leaves_metar_raw_but_prefixed():
    cit = Citation(kind="metar", ref="x", quote="METAR KSFO 120656Z 30007KT 10SM")
    assert premise_for(cit, "KSFO") == "METAR report for KSFO: METAR KSFO 120656Z 30007KT 10SM"
    assert premise_for(cit, None) == "METAR KSFO 120656Z 30007KT 10SM"


# ---------------------------------------------------------------- annotation

def test_claims_annotated_with_best_citation_score_and_threshold():
    v = FakeVerifier(lambda p, h: 0.9 if "28R" in h else 0.1)
    b = with_verification(_briefing(), v, threshold=0.5)
    c = b.findings[0].claims[0]
    assert c.verified is True and c.entailment_score == 0.9
    assert summary(b) == {"checked": 1, "passed": 1, "failed": 0}
    assert b.grounded


def test_failed_claims_are_marked_not_dropped():
    v = FakeVerifier(lambda p, h: 0.05)
    b = with_verification(_briefing(), v)
    assert len(b.findings[0].claims) == 1                       # still there
    assert b.findings[0].claims[0].verified is False and not b.grounded
    assert [c.text for _, c in unverified(b)] == [b.findings[0].claims[0].text]


def test_no_verifier_leaves_claims_untouched():
    b = with_verification(_briefing(), None)
    assert b.findings[0].claims[0].verified is None


def test_precedent_claims_are_out_of_scope():
    from preflight.schemas import Claim

    b = _briefing()
    f = b.findings[0]
    prec = Claim(text="1 prior report describes …",
                 citations=(Citation(kind="asrs", ref="1", quote="narrative"),))
    b = b.model_copy(update={"findings": (f.model_copy(update={"claims": (*f.claims, prec)}),)})
    v = FakeVerifier(lambda p, h: 0.99)
    out = with_verification(b, v)
    assert out.findings[0].claims[1].verified is None            # not sent to the model
    assert all("narrative" not in p for p, _ in v.pairs)


# ---------------------------------------------------------------- corruptions

def test_corruptions_are_material_and_one_per_claim():
    assert corrupt("KSFO — Runway 28R closed until 11 Sep 0700Z.") == (
        "KSFO — Runway 28R open until 11 Sep 0700Z.", "closed→open")
    assert corrupt("PAPI 28L unserviceable.")[1] == "unserviceable→serviceable"
    assert corrupt("Runway 28R available.")[1] == "runway side R→L"
    assert corrupt("Runway 8 available.")[0] == "Runway 17 available."
    assert corrupt("KSFO is reporting VFR: wind 300/7 kt, vis 10 SM.")[1] == "wind 7→25 kt"
    assert corrupt("median arrival delay at KJFK was -1 min")[1] == "median -1→44 min"
    assert corrupt("valid at 11 Sep 0700Z")[1] == "time 07→13Z"
    assert corrupt("nothing material here") is None


# ---------------------------------------------------------------- numeric gate

def test_numbers_extraction_normalises_times_and_signs():
    from preflight.verify.ground import numbers

    assert numbers("until 11 Sep 0700Z, median -1 min, 80% of hours") == {11.0, 700.0, -1.0, 80.0}
    assert numbers("07:00Z") == numbers("0700Z")
    assert numbers("Runway 28R") == {28.0}
    assert numbers("no figures here") == set()


def test_figures_must_appear_in_the_evidence():
    from preflight.verify.ground import figures_supported

    ev = "median arrival delay -1 min; 80% of hours within -15 to 33 min; about 17 arrivals"
    assert figures_supported("median delay -1 min, 80% within -15…33", ev)
    assert not figures_supported("median delay 44 min", ev)          # fabricated figure
    assert figures_supported("nothing numeric", ev)


def test_numeric_gate_overrides_a_confident_model():
    """NLI said 0.98 for 'median 44 min' against evidence saying −1 — the gate must not."""
    v = FakeVerifier(lambda p, h: 0.98)
    b = _briefing()
    f = b.findings[0]
    forged = f.claims[0].model_copy(update={"text": "KSFO — Runway 99R closed until 11 Sep 0700Z."})
    b = b.model_copy(update={"findings": (f.model_copy(update={"claims": (forged,)}),)})
    out = with_verification(b, v)
    assert out.findings[0].claims[0].verified is False         # 99 is not in the evidence
