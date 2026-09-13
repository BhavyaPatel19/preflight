"""Plain-text rendering of a briefing, for the CLI and for eyeballing evals."""

from __future__ import annotations

from preflight.schemas import Briefing, Severity

_TAG = {Severity.HIGH: "HIGH", Severity.MEDIUM: "MED ", Severity.LOW: "LOW ", Severity.INFO: "INFO"}


def render_text(b: Briefing) -> str:
    r = b.request
    route = f"{r.departure} → {r.destination}"
    if r.alternates:
        route += f" (alt {', '.join(r.alternates)})"
    head = f"{route}  ·  {r.aircraft_type or '—'}  ·  off-block {r.off_block:%d %b %H%M}Z"
    counts = f"{len(b.findings)} finding{'s' if len(b.findings) != 1 else ''} · " \
             f"{len(b.abstentions)} abstention{'s' if len(b.abstentions) != 1 else ''}"
    lines = [head, counts, "─" * max(len(head), len(counts))]

    for f in b.ranked():
        phases = ", ".join(p.value for p in f.phases)
        lines.append(f"[{_TAG[f.severity]}] {f.category.upper():<12} {f.headline}")
        lines.append(f"       {phases}")
        for c in f.claims:
            refs = " ".join(f"[{cit.kind}:{cit.ref}]" for cit in c.citations)
            if c.verified is True:
                refs += f"  ✓ grounded {c.entailment_score:.2f}"
            elif c.verified is False:
                refs += f"  ✗ UNVERIFIED {c.entailment_score:.2f}"
            prefix = "   ✎   " if c.author == "llm" else "       "
            lines.append(f"{prefix}{c.text}")
            lines.append(f"       {refs}")
        lines.append("")

    for a in b.abstentions:
        lines.append(f"[ ⊘  ] NOT DETERMINED  {a.topic}")
        lines.append(f"       {a.detail}  [{a.reason}]")
        lines.append("")

    lines.append(f"sources considered: {b.sources_considered} · {b.latency_ms} ms")
    return "\n".join(lines)
