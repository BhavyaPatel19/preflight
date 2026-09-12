"""Prompt-injection detection for NOTAM text.

A NOTAM is telegraphic, upper-case, and about aerodromes. Text that talks to a
model — "ignore previous instructions", role tags, requests to report no
hazards, markup, links — does not belong in one. The detector is a set of
transparent signals with weights, not a model: every verdict names the signals
that fired, so a flagged NOTAM can be inspected and the rule argued with.

This is the input side of the defence. The other half is structural: the
deterministic core never executes text, and when the LLM layer arrives, NOTAM
text reaches it inside delimited, spotlighted data blocks with these flags
attached — never as instructions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_SIGNALS: tuple[tuple[str, re.Pattern[str], float], ...] = (
    # Talking to a model
    ("instruction_override",
     re.compile(r"\b(ignore|disregard|forget|override)\b.{0,40}\b(previous|prior|above|all|"
                r"earlier|system|instructions?|rules?|prompt)\b", re.I), 0.6),
    ("role_marker", re.compile(r"(^|\W)(system|assistant|user|developer|human|ai)\s*:", re.I), 0.5),
    ("persona", re.compile(r"\byou are (now|a|an|the)\b|\bact as\b|\bpretend\b|\brole[- ]?play\b",
                           re.I), 0.5),
    ("model_address", re.compile(r"\b(claude|chatgpt|gpt|llm|language model|the model|the ai|"
                                 r"assistant)\b", re.I), 0.5),
    # Manipulating the output
    ("output_steer",
     re.compile(r"\b(report|say|state|respond|answer|output|tell|confirm)\b.{0,50}\b(no hazards?|"
                r"nothing|safe|all clear|normal|vfr|open|no action)\b", re.I), 0.6),
    ("all_clear_phrase", re.compile(r"\b(no action required|nothing to (brief|report)|"
                                    r"no hazards?)\b", re.I), 0.3),
    ("suppress", re.compile(r"\b(omit|hide|remove|suppress|do not (mention|include|report|cite))\b",
                            re.I), 0.5),
    ("format_hijack",
     re.compile(r"\bjson\b|\bmarkdown\b|```|<\/?[a-z]+>|\[/?INST\]|<<?/?SYS>>?", re.I), 0.5),
    ("json_structure", re.compile(r"\{\s*\"[a-z_]+\"\s*:"), 0.3),
    # Exfiltration / tools
    ("url", re.compile(r"https?://|www\.|\.(com|net|org|io)\b", re.I), 0.4),
    ("tool_call", re.compile(r"\b(call|invoke|run|execute)\b.{0,30}\b(tool|function|command|"
                             r"script|api)\b", re.I), 0.5),
    # Obfuscation
    ("zero_width", re.compile(r"[​‌‍⁠﻿]"), 0.5),
    ("base64_blob", re.compile(r"[A-Za-z0-9+/]{40,}={0,2}"), 0.5),
    ("spaced_letters", re.compile(r"(?:\b[A-Za-z]\s+){6,}"), 0.5),
)

# Leetspeak normalisation: signals are re-run on this copy, and any that fire only
# here add an obfuscation signal as well.
_LEET = str.maketrans(
    {"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"}
)

# NOTAMs are upper-case. A run of lower-case prose is the single strongest tell.
_LOWER_PROSE = re.compile(r"\b[a-z]{3,}(?:\s+[a-z]{2,}){4,}")


@dataclass(frozen=True)
class InjectionVerdict:
    score: float
    signals: tuple[str, ...] = field(default_factory=tuple)

    @property
    def suspicious(self) -> bool:
        return self.score >= 0.5


def detect(text: str) -> InjectionVerdict:
    """Score NOTAM text for injection attempts; 0 = clean, ≥ 0.5 = flag."""
    if not text or not text.strip():
        return InjectionVerdict(0.0)
    fired: list[str] = []
    score = 0.0
    normalised = text.translate(_LEET)
    for name, pattern, weight in _SIGNALS:
        if pattern.search(text):
            fired.append(name)
            score += weight
        elif name not in {"base64_blob", "json_structure"} and pattern.search(normalised):
            fired.extend((name, "leetspeak"))
            score += weight + 0.3
    if _LOWER_PROSE.search(text):
        fired.append("lowercase_prose")
        score += 0.4
    letters = [c for c in text if c.isalpha()]
    if letters:
        lower = sum(1 for c in letters if c.islower()) / len(letters)
        if lower > 0.5:
            fired.append("mostly_lowercase")
            score += 0.2
    return InjectionVerdict(round(min(score, 1.0), 3), tuple(fired))
