"""Claim-level grounding: every claim is checked against the passage it cites.

The premise is the citation's verbatim quote, made readable — NOTAM
contractions expanded, the source named — because the NLI model reads
English, not ICAO shorthand. A claim passes if, against *any* of its
citations, (1) the entailment score clears the threshold **and** (2) every
number in the claim appears in the evidence. The second gate exists because
NLI models are unreliable on figures: with enough surrounding text in common,
"median delay 44 min" scored 0.98 against evidence saying −1 min. Numbers are
checked exactly; semantics are checked by the model.

Scope: factual claims (NOTAM, weather, forecast/climatology). Precedent
claims are descriptive by construction — the quote *is* the passage — and are
left ``verified=None`` until the LLM layer writes prose about them; that is
the moment verification of precedent starts to matter.

Policy: annotate, never drop. In the deterministic core a failed check
means a bug or a verifier miss, and hiding a hazard on a verifier miss would
be the worse failure. The LLM layer is where unsupported claims get dropped.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from time import perf_counter

from preflight.config import settings
from preflight.decode.contractions import expand
from preflight.schemas import Briefing, Citation, Claim, Finding
from preflight.verify.nli import Verifier

VERIFIABLE_KINDS = {"notam", "metar", "taf", "forecast"}

_NUMBER = re.compile(r"-?\d+(?::\d{2})?(?:\.\d+)?")


def numbers(text: str) -> set[float]:
    """Every figure in the text as a value. '07:00' and '0700' are the same number."""
    out: set[float] = set()
    for tok in _NUMBER.findall(text):
        try:
            out.add(float(tok.replace(":", "")))
        except ValueError:
            continue
    return out


def figures_supported(claim_text: str, premise: str) -> bool:
    return numbers(claim_text) <= numbers(premise)

# Plain-language equivalents the NLI model does not know. Appended to NOTAM premises so a
# restatement like "the PAPI is not working" is not rejected on vocabulary.
_NOTAM_GLOSSARY = (" (Here: unserviceable means not working / out of service; closed means"
                   " not available for use; available means usable.)")


def premise_for(cit: Citation, airport: str | None) -> str:
    """A readable premise from a citation's quote."""
    q = cit.quote or ""
    if cit.kind == "notam":
        q = expand(q).replace(" DUE ", " due to ").replace(" AND ", " and ")
        q = q.replace(" BTN ", " between ").replace(" ALTN ", " alternate ")
        q += _NOTAM_GLOSSARY
    if cit.kind == "notam":
        where = f" at {airport}" if airport else ""
        return f"NOTAM {cit.ref}{where} states: {q}"
    if cit.kind == "metar":
        return f"METAR report for {airport}: {q}" if airport else q
    if cit.kind == "forecast":
        return f"Delay statistics for {airport}: {q}" if airport else q
    if airport and not q.startswith(airport):
        q = f"{airport}: {q}"
    return q


def _pairs_for(f: Finding, c: Claim) -> list[tuple[str, str]]:
    return [(premise_for(cit, f.airport), c.text)
            for cit in c.citations if cit.kind in VERIFIABLE_KINDS and cit.quote]


def with_verification(
    briefing: Briefing, verifier: Verifier | None, *, threshold: float | None = None
) -> Briefing:
    """Return the briefing with ``verified`` / ``entailment_score`` set on factual claims."""
    if verifier is None:
        return briefing
    threshold = settings().grounding_threshold if threshold is None else threshold
    t0 = perf_counter()

    # Batch every pair across the briefing, then scatter the scores back.
    jobs: list[tuple[int, int, list[tuple[str, str]]]] = []
    flat: list[tuple[str, str]] = []
    for fi, f in enumerate(briefing.findings):
        for ci, c in enumerate(f.claims):
            pairs = _pairs_for(f, c)
            if pairs:
                jobs.append((fi, ci, pairs))
                flat.extend(pairs)
    scores = verifier.entailment(flat)

    best: dict[tuple[int, int], float] = {}
    k = 0
    for fi, ci, pairs in jobs:
        # A citation with a missing figure cannot support the claim, whatever the model says.
        gated = [s if figures_supported(h, p) else 0.0
                 for (p, h), s in zip(pairs, scores[k:k + len(pairs)], strict=True)]
        best[(fi, ci)] = max(gated)
        k += len(pairs)

    findings: list[Finding] = []
    for fi, f in enumerate(briefing.findings):
        claims: list[Claim] = []
        for ci, c in enumerate(f.claims):
            if (fi, ci) in best:
                s = best[(fi, ci)]
                claims.append(c.model_copy(update={"verified": s >= threshold,
                                                   "entailment_score": round(s, 4)}))
            else:
                claims.append(c)
        findings.append(f.model_copy(update={"claims": tuple(claims)}))

    return briefing.model_copy(update={
        "findings": tuple(findings),
        "latency_ms": (briefing.latency_ms or 0) + int((perf_counter() - t0) * 1000),
    })


def load_verifier() -> Verifier | None:
    """The real model, or None without the ML extras."""
    try:
        import transformers  # noqa: F401
    except ImportError:
        return None
    from preflight.verify.nli import HFVerifier

    return HFVerifier()


def unverified(briefing: Briefing) -> list[tuple[Finding, Claim]]:
    return [(f, c) for f in briefing.findings for c in f.claims if c.verified is False]


def summary(briefing: Briefing) -> dict[str, int]:
    checked = [c for f in briefing.findings for c in f.claims if c.verified is not None]
    return {"checked": len(checked), "passed": sum(1 for c in checked if c.verified),
            "failed": sum(1 for c in checked if c.verified is False)}


__all__: Sequence[str] = (
    "premise_for", "with_verification", "load_verifier", "unverified", "summary",
    "numbers", "figures_supported",
)
