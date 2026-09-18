"""Label scheme shared by the generator, the gold set, the model and the eval."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Entity types the extractor tags. The eight are ``schemas.EntityType``; TIME is the
# schedule/validity text that lives inside NOTAM bodies (US-domestic windows, D) items).
TYPES: tuple[str, ...] = (
    "RWY", "TWY", "NAVAID", "LIGHTING", "OBSTACLE", "AIRSPACE", "SERVICE", "APRON", "TIME",
)
TAGS: tuple[str, ...] = ("O", *(f"{p}-{t}" for t in TYPES for p in ("B", "I")))
TAG_ID: dict[str, int] = {t: i for i, t in enumerate(TAGS)}

_TOKEN = re.compile(r"[A-Za-z0-9]+(?:[/\-.:][A-Za-z0-9]+)*|[^\sA-Za-z0-9]")


@dataclass(frozen=True)
class Span:
    start: int
    end: int
    type: str

    def overlaps(self, other: Span) -> bool:
        return self.start < other.end and other.start < self.end


def tokenize(text: str) -> list[tuple[str, int, int]]:
    """Whitespace/punctuation tokens with character offsets; ``28R``, ``ILS/DME`` and
    ``0600-1400`` stay whole."""
    return [(m.group(), m.start(), m.end()) for m in _TOKEN.finditer(text)]


def bio_tags(text: str, spans: list[Span]) -> tuple[list[str], list[str]]:
    """Tokens and their BIO tags from character spans (first token in a span is B-)."""
    toks = tokenize(text)
    tags = ["O"] * len(toks)
    for sp in sorted(spans, key=lambda s: s.start):
        first = True
        for i, (_, s, e) in enumerate(toks):
            if s < sp.end and e > sp.start:
                tags[i] = f"{'B' if first else 'I'}-{sp.type}"
                first = False
    return [t for t, _, _ in toks], tags


def spans_from_tags(text: str, tags: list[str]) -> list[Span]:
    """Inverse of ``bio_tags`` over the same tokenisation (I- after O starts a new span)."""
    toks = tokenize(text)
    out: list[Span] = []
    cur: Span | None = None
    for (_, s, e), tag in zip(toks, tags, strict=True):
        if tag == "O":
            if cur:
                out.append(cur)
            cur = None
            continue
        prefix, typ = tag.split("-", 1)
        if cur is not None and prefix == "I" and cur.type == typ:
            cur = Span(cur.start, e, typ)
        else:
            if cur:
                out.append(cur)
            cur = Span(s, e, typ)
    if cur:
        out.append(cur)
    return out
