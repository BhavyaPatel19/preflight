"""Precedent: what happened to other crews in these conditions.

For each finding that warrants it, search the ASRS/NTSB corpus for prior
reports at that airport and attach a second, cited claim. This is the
"Recall" module of the spec, and it is still deterministic: the query is
built from the finding's decoded entities, the search is the measured hybrid
retriever, and only hits above a reranker score the eval showed to be
meaningful are attached. Every citation carries the verbatim passage.

If the retrieval models are not available the briefing says so — an
abstention — rather than silently omitting precedent.
"""

from __future__ import annotations

import re
from time import perf_counter
from typing import Any

from psycopg import Connection

from preflight.config import settings
from preflight.retrieval.search import Hit, Retriever
from preflight.schemas import Abstention, Briefing, Citation, Claim, Finding, Severity

_PREFIX = re.compile(r"^[A-Z]{4}:\s*")
_TAIL = re.compile(r"\s+(until\s.+|,\s*permanent)$")
_CORPUS_KINDS = {"asrs": "asrs", "ntsb": "ntsb", "ops_note": "ops_note", "far_aim": "far_aim"}

_WX_QUERY = {
    "LIFR": "approach and landing in very low visibility and low ceiling",
    "IFR": "instrument approach in low visibility",
}

# What goes wrong for crews when this kind of NOTAM is in force. The query has to
# describe the operational consequence, not the NOTAM: "ILS unserviceable
# maintenance" retrieves maintenance stories; "flew a different approach after the
# ILS went out" retrieves the precedent. These templates are the deterministic
# stand-in for the Sprint 4 query rewriter, and the Sprint 5 judged set will say
# how good they are.
_SCENARIO = {
    "runway": "runway closed, crew used the parallel runway, lined up with the wrong runway "
              "or a taxiway, confusion over which runway was in use",
    "taxiway": "taxiway closed, ground reroute, wrong taxiway taken or hold short missed "
               "during taxi",
    "approach aids": "ILS out of service, flew an RNAV or visual approach instead, late "
                     "change of approach, glidepath or minimums confusion",
    "lighting": "approach lights or PAPI out of service, night visual approach, glidepath "
                "judgment, unstable approach",
    "navaid": "navigation aid out of service, navigation error, wrong fix or course",
    "airspace": "temporary flight restriction, airspace incursion, entered restricted "
                "airspace without clearance",
    "obstacle": "crane or obstacle near the runway, terrain or obstacle clearance on "
                "departure or approach",
    "surface": "apron or ramp closure, ground congestion, ground collision",
}


def precedent_query(f: Finding) -> str | None:
    """The search query for a finding, or None when precedent would not help."""
    if f.category == "weather":
        cat = f.headline.split(":", 1)[-1].strip().split(" ")[0].upper()
        return _WX_QUERY.get(cat)
    if f.category in {"forecast"} or f.severity not in {Severity.HIGH, Severity.MEDIUM}:
        return None
    specifics = _TAIL.sub("", _PREFIX.sub("", f.headline))
    specifics = specifics.replace("(", "").replace(")", "").strip()
    scenario = _SCENARIO.get(f.category)
    return f"{specifics}. {scenario}" if scenario else (specifics or None)


def _citation(h: Hit) -> Citation:
    return Citation(kind=_CORPUS_KINDS.get(h.source, "asrs"),  # type: ignore[arg-type]
                    ref=h.external_id, quote=h.text[:240])


def _describe(h: Hit) -> str:
    # ASRS titles are analyst synopses — good descriptions. NTSB titles are case ids;
    # the passage itself says more.
    text = h.title if (h.source == "asrs" and h.title) else h.text
    text = " ".join(text.split())
    return (text[:140].rstrip() + "…") if len(text) > 140 else text.rstrip(".")


def precedent_claim(hits: list[Hit], airport: str | None) -> Claim | None:
    """One claim describing the prior reports, honest about where they happened."""
    if not hits:
        return None
    here = [h for h in hits if airport and h.icao == airport]
    elsewhere = [h for h in hits if h not in here]
    parts: list[str] = []
    if here:
        parts.append(f"{len(here)} prior report{'s' if len(here) != 1 else ''} at {airport}")
    if elsewhere:
        parts.append(f"{len(elsewhere)} prior report{'s' if len(elsewhere) != 1 else ''} "
                     "with no airport recorded")
    lead = " and ".join(parts)
    verb = "describe" if len(hits) != 1 else "describes"
    quoted = "; ".join(f"“{_describe(h)}”" for h in hits)
    text = f"{lead} {verb} similar conditions: {quoted}."
    return Claim(text=text, citations=tuple(_citation(h) for h in hits))


def with_precedent(
    conn: Connection[Any],
    briefing: Briefing,
    retriever: Retriever | None,
    *,
    k: int | None = None,
    min_score: float | None = None,
) -> Briefing:
    """Return a briefing with precedent claims attached where warranted."""
    t0 = perf_counter()
    k = k or settings().precedent_k
    min_score = settings().precedent_min_score if min_score is None else min_score

    if retriever is None:
        gap = Abstention(
            topic="precedent", reason="no_coverage",
            detail="Retrieval models are not available in this environment; no prior-report "
                   "search was run.",
        )
        return briefing.model_copy(update={"abstentions": (*briefing.abstentions, gap)})

    findings: list[Finding] = []
    considered = 0
    seen: set[str] = set()
    for f in briefing.findings:
        q = precedent_query(f)
        if q is None:
            findings.append(f)
            continue
        hits = retriever.search(conn, q, k=k, icao=f.airport, rerank=True)
        considered += len(hits)
        keep = [h for h in hits
                if (h.rerank_score or 0.0) >= min_score and h.external_id not in seen]
        for h in keep:
            seen.add(h.external_id)
        claim = precedent_claim(keep, f.airport)
        findings.append(f.model_copy(update={"claims": (*f.claims, claim)}) if claim else f)

    extra_ms = int((perf_counter() - t0) * 1000)
    return briefing.model_copy(update={
        "findings": tuple(findings),
        "sources_considered": briefing.sources_considered + considered,
        "latency_ms": (briefing.latency_ms or 0) + extra_ms,
    })


def load_retriever() -> Retriever | None:
    """The real models, or None if the ML extras are not installed."""
    try:
        from preflight.retrieval.embed import STEmbedder, STReranker
    except ImportError:
        return None
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return None
    return Retriever(STEmbedder(), STReranker())
