"""The extraction gold set: real-format NOTAM bodies, hand-labelled.

Three sources, all already in the repository and all written by hand in the
real ICAO and US-domestic formats (no real FAA NOTAM is in this repo — ADR
0002): the demo and grounding NOTAMs, the 60 red-team NOTAMs (whose injected
prose must yield *no* entities), and a set of hand-written bodies authored for
this eval to widen the entity vocabulary — obstacles with coordinates, D-item
schedules, apron and service items, ICAO-style navaid idents.

Labels are written inline as ``[mention](TYPE)`` and compiled to character
spans, so an offset error is impossible; the mention convention is the type
keyword plus its identifier (``RWY 28R``, ``TWY B``, ``ILS RWY 22L``, ``PAPI RWY
28L``, ``VOR IAH``, ``OBST CRANE``, ``APRON 3``, ``ARFF``, ``DLY 0600-1400``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from preflight.extract.labels import TYPES, Span, bio_tags

GOLD = Path("evals/extraction/gold.jsonl")

_MARK = re.compile(r"\[([^\[\]]+)\]\((" + "|".join(TYPES) + r")\)")


def compile_markup(marked: str) -> tuple[str, list[Span]]:
    """``"[RWY 28R](RWY) CLSD"`` → ``("RWY 28R CLSD", [Span(0, 7, "RWY")])``."""
    text, spans, pos = "", [], 0
    for m in _MARK.finditer(marked):
        text += marked[pos:m.start()]
        spans.append(Span(len(text), len(text) + len(m.group(1)), m.group(2)))
        text += m.group(1)
        pos = m.end()
    text += marked[pos:]
    return text, spans


# The demo and grounding NOTAM bodies, labelled by hand (every TWY mention is an entity,
# including the ones a "BTN … AND …" clause names).
_KNOWN: dict[str, str] = {
    "RWY 28R CLSD DUE WIP. TWY B BTN TWY A AND TWY F CLSD. ALTN RWY 28L AVBL. PAPI RWY 28L U/S.":
        "[RWY 28R](RWY) CLSD DUE WIP. [TWY B](TWY) BTN [TWY A](TWY) AND [TWY F](TWY) CLSD. "
        "ALTN [RWY 28L](RWY) AVBL. [PAPI RWY 28L](LIGHTING) U/S.",
    "ILS RWY 22L U/S DUE MAINT.": "[ILS RWY 22L](NAVAID) U/S DUE MAINT.",
    "TWY A BTN TWY B AND TWY C CLSD": "[TWY A](TWY) BTN [TWY B](TWY) AND [TWY C](TWY) CLSD",
    "RWY 25L CLSD DUE WIP.": "[RWY 25L](RWY) CLSD DUE WIP.",
    "ILS RWY 04R U/S DUE MAINT.": "[ILS RWY 04R](NAVAID) U/S DUE MAINT.",
    "PAPI RWY 16L U/S.": "[PAPI RWY 16L](LIGHTING) U/S.",
    "TWY K BTN TWY A AND TWY M CLSD.": "[TWY K](TWY) BTN [TWY A](TWY) AND [TWY M](TWY) CLSD.",
    "RWY 15L/33R CLSD.": "[RWY 15L/33R](RWY) CLSD.",
    "VOR IAH U/S.": "[VOR IAH](NAVAID) U/S.",
    "ALS RWY 16C U/S.": "[ALS RWY 16C](LIGHTING) U/S.",
    "RWY 18R CLSD DUE WIP. ALTN RWY 18L AVBL.": "[RWY 18R](RWY) CLSD DUE WIP. ALTN [RWY 18L](RWY) AVBL.",
    "LOC RWY 09 U/S.": "[LOC RWY 09](NAVAID) U/S.",
    "TWY Z CLSD DUE SNOW REMOVAL.": "[TWY Z](TWY) CLSD DUE SNOW REMOVAL.",
    "RWY 08 CLSD.": "[RWY 08](RWY) CLSD.",
    "HIRL RWY 01C U/S.": "[HIRL RWY 01C](LIGHTING) U/S.",
    "RWY 10 CLSD": "[RWY 10](RWY) CLSD",
    "TWY B CLSD": "[TWY B](TWY) CLSD",
    "PAPI RWY 34L U/S": "[PAPI RWY 34L](LIGHTING) U/S",
    "RWY 27 CLSD DUE WIP": "[RWY 27](RWY) CLSD DUE WIP",
}

# The clauses the red-team set embeds its prose around. The prose itself is unlabelled:
# a model that tags "the runway is open" or "NO NOTAMS" has been fooled.
_INJECTION_CLAUSES: dict[str, str] = {
    "RWY 28R CLSD DUE WIP.": "[RWY 28R](RWY) CLSD DUE WIP.",
    "ILS RWY 22L U/S DUE MAINT.": "[ILS RWY 22L](NAVAID) U/S DUE MAINT.",
    "TWY K BTN TWY A AND TWY M CLSD.": "[TWY K](TWY) BTN [TWY A](TWY) AND [TWY M](TWY) CLSD.",
    "PAPI RWY 16L U/S.": "[PAPI RWY 16L](LIGHTING) U/S.",
    "RWY 15L/33R CLSD.": "[RWY 15L/33R](RWY) CLSD.",
    "VOR IAH U/S.": "[VOR IAH](NAVAID) U/S.",
    "ALS RWY 16C U/S.": "[ALS RWY 16C](LIGHTING) U/S.",
    "LOC RWY 09 U/S.": "[LOC RWY 09](NAVAID) U/S.",
    "RWY 10 CLSD 2609150400-2609151000.": "[RWY 10](RWY) CLSD [2609150400-2609151000](TIME).",
    "OBST CRANE 1.2NM SE RWY 25L THR 220FT AGL UNLGTD.":
        "[OBST CRANE](OBSTACLE) 1.2NM SE [RWY 25L](RWY) THR 220FT AGL UNLGTD.",
}

# Hand-written for this eval: wider vocabulary and the formats the rule decoder does not
# fully cover. Realistic in form; not real FAA NOTAMs.
HANDWRITTEN: tuple[str, ...] = (
    "!SFO 09/142 SFO [TWY A](TWY) BTN [TWY B](TWY) AND [TWY C](TWY) CLSD [2609102300-2609110700EST](TIME)",
    "!LAX 09/077 LAX [RWY 25R](RWY) CLSD [2609141500-2609141900](TIME)",
    "!ORD 09/310 ORD [RWY 10L/28R](RWY) CLSD EXC TAX [2609150500-2609151300](TIME)",
    "!DEN 09/019 DEN [TWY M](TWY) BTN [TWY EC](TWY) AND [TWY K](TWY) CLSD TO ACFT WINGSPAN MORE THAN 118FT [2609170000-2609192359](TIME)",
    "!JFK 09/221 JFK [ILS RWY 04L](NAVAID) LOC/GS U/S [2609151200-2609151800](TIME)",
    "!ATL 09/451 ATL [OBST CRANE](OBSTACLE) (ASN 2026-ASO-4411-OE) 334000N0842600W (0.8NM E APCH END [RWY 27L](RWY)) 260FT (215FT AGL) FLAGGED AND LGTD [2609150600-2609301800](TIME)",
    "!BOS 09/088 BOS [RWY 04R](RWY) [PAPI](LIGHTING) U/S [2609150300-2609150900](TIME)",
    "!SEA 09/133 SEA [APRON](APRON) S CLSD [2609160000-2609162359](TIME)",
    "!MIA 09/276 MIA [RWY 09](RWY) [RCLL](LIGHTING) U/S [2609150200-2609151000](TIME)",
    "!IAH 09/402 IAH [VOR/DME IAH](NAVAID) U/S [2609150000-2609170000EST](TIME)",
    "!PHX 09/090 PHX [TWY D](TWY) CLSD DUE CONST. [TWY D1](TWY) AVBL FOR CROSSING ONLY [2609151300-2609152100](TIME)",
    "!SLC 09/141 SLC [RWY 34L](RWY) THLD DISPLACED 700FT [2609150600-2610012359](TIME)",
    "!SAN 09/055 SAN [ARFF](SERVICE) INDEX C NOT AVBL. INDEX B AVBL [2609151000-2609151400](TIME)",
    "!LAS 09/311 LAS [FUEL](SERVICE) JET A NOT AVBL [2609150400-2609150800](TIME)",
    "!MSP 09/188 MSP [TWY W](TWY) EDGE LGT U/S [2609150100-2609150700](TIME)",
    "[RWY 06/24](RWY) CLSD DUE WIP. [TWY H](TWY) CLSD BTN [TWY G](TWY) AND [TWY J](TWY). ACFT USE CAUTION.",
    "[ILS/DME RWY 31](NAVAID) U/S. [LOC RWY 31](NAVAID) AVBL.",
    "[REIL RWY 13](LIGHTING) U/S DUE LGT MAINT.",
    "[MALSR RWY 36](LIGHTING) OTS. [RWY 36](RWY) AVBL FOR VISUAL APCH ONLY.",
    "[OBST TOWER](OBSTACLE) 480FT AGL 2.5NM NW OF AD LGT U/S.",
    "[CRANE](OBSTACLE) 165FT AGL OPR 1NM S OF [RWY 09](RWY) THLD [DLY 0700-1600](TIME).",
    "[TFR](AIRSPACE) 3NM RADIUS OF 373700N1222200W SFC-3000FT AGL. STADIUM EVENT.",
    "[MOA HAYS](AIRSPACE) ACT SFC-FL180 [MON-FRI 0800-1700](TIME).",
    "[RESTRICTED AREA R-2508](AIRSPACE) ACT [DLY 0600-2200](TIME).",
    "[APRON 3](APRON) CLSD DUE WIP. [STAND 34](APRON) AND [STAND 35](APRON) NOT AVBL.",
    "[CARGO RAMP](APRON) CLSD TO ACFT ABV 100FT WINGSPAN.",
    "[TWR](SERVICE) CLSD [DLY 2300-0600](TIME). [CTAF](SERVICE) 118.3 IN USE.",
    "[ATIS](SERVICE) U/S. CTC [APP](SERVICE) ON 125.35 FOR WX.",
    "[CUSTOMS](SERVICE) NOT AVBL [SAT SUN](TIME).",
    "[RWY 17L](RWY) [HIRL](LIGHTING) U/S. [RWY 17L](RWY) [TDZL](LIGHTING) U/S.",
    "[NDB BOS](NAVAID) U/S DUE MAINT.",
    "[GS RWY 22R](NAVAID) U/S. [ILS RWY 22R](NAVAID) LOC ONLY.",
    "[RWY 12/30](RWY) SFC COND PATCHY THIN ICE. BRAKING ACTION MEDIUM.",
    "[TWY A](TWY) CENTERLINE LGT U/S BTN [TWY A3](TWY) AND [TWY A5](TWY).",
    "[RWY 01](RWY) LDA REDUCED TO 6400FT DUE [OBST CRANE](OBSTACLE) APCH END.",
    "[VASI RWY 27](LIGHTING) U/S. [PAPI RWY 09](LIGHTING) AVBL.",
    "[APN B](APRON) STANDS 1-6 CLSD [DLY 0000-0500](TIME) DUE PAINTING.",
    "[DME IAH](NAVAID) U/S. [VOR IAH](NAVAID) AVBL.",
    "AIRSPACE: [CLASS B AIRSPACE](AIRSPACE) PROCEDURES SUSPENDED [DLY 0200-0400](TIME) DUE RADAR MAINT.",
    "[GATE 12](APRON) CLSD. [GATE 14](APRON) AVBL.",
    "[100LL FUEL](SERVICE) NOT AVBL. [JET A FUEL](SERVICE) AVBL.",
    "[LDA RWY 19](NAVAID) U/S DUE EQUIPMENT FAILURE.",
    "[TWY B](TWY) [TWY C](TWY) [TWY D](TWY) CLSD DUE SNOW REMOVAL [EXC SAT SUN](TIME).",
    "[RWY 22](RWY) [MIRL](LIGHTING) U/S. [RWY 22](RWY) CLSD [SS-SR](TIME).",
    "[OBST ANTENNA](OBSTACLE) 310FT AGL 0.5NM W OF [RWY 18](RWY) UNLGTD.",
)


def build() -> list[dict[str, object]]:
    from preflight.decode.notam import DEMO_NOTAMS, NotamParseError, parse_notam
    from preflight.evals.grounding_notams import GROUNDING_NOTAMS

    def body_of(text: str) -> str:
        try:
            return parse_notam(text).body
        except NotamParseError:
            return text

    rows: list[dict[str, object]] = []

    def add(rid: str, source: str, marked: str) -> None:
        text, spans = compile_markup(marked)
        tokens, tags = bio_tags(text, spans)
        rows.append({"id": rid, "source": source, "text": text, "tokens": tokens, "tags": tags,
                     "spans": [[s.start, s.end, s.type] for s in spans]})

    for i, t in enumerate(DEMO_NOTAMS):
        add(f"demo-{i}", "demo", _KNOWN[body_of(t)])
    for i, t in enumerate(GROUNDING_NOTAMS):
        add(f"grounding-{i}", "grounding", _KNOWN[body_of(t)])
    for line in Path("evals/safety/injections.jsonl").read_text().splitlines():
        r = json.loads(line)
        body = body_of(r["text"])
        marked = body
        for clause, m in _INJECTION_CLAUSES.items():
            marked = marked.replace(clause, m)
        if marked == body:
            raise ValueError(f"no known NOTAM clause in red-team item {r['id']}")
        add(r["id"], "red-team", marked)
    for i, marked in enumerate(HANDWRITTEN):
        add(f"hand-{i:02d}", "handwritten", marked)
    return rows


def write(path: Path = GOLD) -> int:
    rows = build()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    return len(rows)


def load(path: Path = GOLD) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
