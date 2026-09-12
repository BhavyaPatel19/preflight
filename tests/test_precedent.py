"""Precedent attachment: query building and claim wording are pure; attachment uses fakes."""

from datetime import UTC, datetime, timedelta, timezone

from preflight.brief.core import _fmt, notam_findings
from preflight.brief.precedent import precedent_claim, precedent_query, with_precedent
from preflight.decode.notam import DEMO_NOTAMS, parse_notam
from preflight.retrieval.search import Hit, Retriever
from preflight.schemas import Briefing, Finding, FlightRequest, Severity

T0 = datetime(2026, 9, 11, 2, 30, tzinfo=UTC)


def _hit(ext, text, *, icao=None, source="asrs", title=None, score=0.9):
    return Hit(chunk_id=0, document_id=0, source=source, external_id=ext, title=title,
               ordinal=0, text=text, icao=icao, fused_score=0.01, in_dense=True,
               in_lexical=False, rerank_score=score)


# ---------------------------------------------------------------- the timezone bug

def test_fmt_renders_utc_whatever_tz_the_driver_returns():
    pdt = timezone(timedelta(hours=-7))
    assert _fmt(datetime(2026, 9, 11, 0, 0, tzinfo=pdt)) == "11 Sep 0700Z"
    assert _fmt(datetime(2026, 9, 11, 7, 0, tzinfo=UTC)) == "11 Sep 0700Z"
    assert _fmt(None) == "?"


# ---------------------------------------------------------------- queries

def test_precedent_query_is_specifics_plus_operational_scenario():
    f = notam_findings("KSFO", "departure", [parse_notam(DEMO_NOTAMS[0])])[0]
    q = precedent_query(f)
    assert q.startswith("Runway 28R closed work in progress. ")     # airport + validity stripped
    assert "lined up with the wrong runway" in q          # the consequence, not the NOTAM


def test_precedent_query_only_for_actionable_findings():
    claims = notam_findings("KSFO", "departure", [parse_notam(DEMO_NOTAMS[0])])[0].claims
    info = Finding(category="notam", severity=Severity.INFO, headline="KSFO: 3 further NOTAMs",
                   claims=claims)
    assert precedent_query(info) is None
    fc = Finding(category="forecast", severity=Severity.INFO, headline="KJFK: TAF valid …",
                 claims=info.claims)
    assert precedent_query(fc) is None


def test_weather_query_only_for_low_visibility_categories():
    base = notam_findings("KSFO", "departure", [parse_notam(DEMO_NOTAMS[0])])[0]
    lifr = Finding(category="weather", severity=Severity.HIGH,
                   headline="KJFK: LIFR — ceiling 200 ft", claims=base.claims)
    vfr = Finding(category="weather", severity=Severity.INFO, headline="KSFO: VFR — wind calm",
                  claims=base.claims)
    assert "low visibility" in precedent_query(lifr)
    assert precedent_query(vfr) is None


# ---------------------------------------------------------------- claim wording

def test_claim_separates_at_airport_from_unrecorded():
    hits = [_hit("1", "narrative one", icao="KSFO", title="Crew lined up with taxiway C at night."),
            _hit("2", "an NTSB passage about a runway excursion.", source="ntsb",
                 title="X — Y — 2010")]
    c = precedent_claim(hits, "KSFO")
    assert c.text.startswith(
        "1 prior report at KSFO and 1 prior report with no airport recorded describe"
    )
    assert "“Crew lined up with taxiway C at night”" in c.text          # ASRS: synopsis
    assert "“an NTSB passage about a runway excursion”" in c.text    # NTSB: passage, not id
    assert [cit.kind for cit in c.citations] == ["asrs", "ntsb"]
    assert c.citations[0].quote == "narrative one"


def test_claim_singular_and_none():
    assert precedent_claim([], "KSFO") is None
    c = precedent_claim([_hit("1", "t", icao="KSFO", title="One report.")], "KSFO")
    assert c.text.startswith("1 prior report at KSFO describes")


# ---------------------------------------------------------------- attachment

class _Retriever(Retriever):
    def __init__(self, hits):
        self._hits = hits
        self.calls = []

    def search(self, conn, query, **kw):
        self.calls.append((query, kw.get("icao")))
        return self._hits


def _briefing():
    f = notam_findings("KSFO", "departure", [parse_notam(DEMO_NOTAMS[0])])
    return Briefing(request=FlightRequest(departure="KSFO", destination="KJFK", off_block=T0),
                    generated_at=T0, findings=tuple(f), sources_considered=1, latency_ms=5)


def test_attaches_only_hits_above_threshold_and_updates_counts():
    r = _Retriever([_hit("a", "good", icao="KSFO", title="Good", score=0.9),
                    _hit("b", "weak", icao="KSFO", title="Weak", score=0.2)])
    out = with_precedent(None, _briefing(), r, min_score=0.5)
    f = out.findings[0]
    assert len(f.claims) == 2 and [c.ref for c in f.claims[1].citations] == ["a"]
    assert len(r.calls) == 1 and r.calls[0][1] == "KSFO"
    assert r.calls[0][0].startswith("Runway 28R closed work in progress. ")
    assert out.sources_considered == 3 and out.latency_ms >= 5
    assert out.grounded                                              # citations, no verifier yet


def test_no_hits_leaves_finding_untouched():
    out = with_precedent(None, _briefing(), _Retriever([]))
    assert len(out.findings[0].claims) == 1


def test_missing_retriever_is_an_abstention_not_silence():
    out = with_precedent(None, _briefing(), None)
    assert len(out.findings[0].claims) == 1
    assert [a.topic for a in out.abstentions] == ["precedent"]
    assert out.abstentions[0].reason == "no_coverage"


def test_same_report_not_cited_twice_across_findings():
    b = _briefing()
    two = Briefing(**{**b.model_dump(), "findings": (b.findings[0], b.findings[0])})
    r = _Retriever([_hit("dup", "t", icao="KSFO", title="Dup")])
    out = with_precedent(None, two, r)
    assert len(out.findings[0].claims) == 2 and len(out.findings[1].claims) == 1
