"""Sentence-aware chunking.

Targets ~1,000 characters (~250 tokens) per chunk, never splits a sentence, and
carries the last sentence of one chunk into the next so a fact that straddles a
boundary survives in at least one chunk whole.
"""

from __future__ import annotations

import re
from typing import NamedTuple

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
_WS = re.compile(r"\s+")


class Chunk(NamedTuple):
    ordinal: int
    text: str


def sentences(text: str) -> list[str]:
    text = _WS.sub(" ", text).strip()
    return [s for s in _SENTENCE.split(text) if s] if text else []


def chunk_text(text: str, *, target: int = 1000, overlap: bool = True) -> list[Chunk]:
    """Split ``text`` into sentence-aligned chunks of roughly ``target`` characters."""
    sents = sentences(text)
    if not sents:
        return []

    chunks: list[Chunk] = []
    buf: list[str] = []
    size = 0
    carried = False          # buf holds only the overlap sentence from the previous chunk
    for s in sents:
        # A single sentence longer than the target becomes its own chunk.
        if buf and not carried and size + len(s) + 1 > target:
            chunks.append(Chunk(len(chunks), " ".join(buf)))
            if overlap and len(buf[-1]) < target // 2:
                buf, carried = [buf[-1]], True
            else:
                buf, carried = [], False
            size = sum(len(b) + 1 for b in buf)
        buf.append(s)
        carried = False
        size += len(s) + 1
    if buf:
        chunks.append(Chunk(len(chunks), " ".join(buf)))
    return chunks
