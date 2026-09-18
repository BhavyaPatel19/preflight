"""Synthetic NOTAM bodies with known entity spans.

Each clause template writes one thing a NOTAM says — a runway closed, an ILS
unserviceable, a crane near a threshold — and records exactly where the entity
mention sits in the text, so the labels are correct by construction. Bodies
combine one to four clauses in ICAO ``E)`` style or US-domestic style, in the
contraction vocabulary the rule decoder expands, with distractor clauses that
mention nothing taggable. The vocabulary is deliberately wider than the rule
decoder's regexes, so the model has something to learn that the rules do not
already do.

This is training data. It is not evidence about real NOTAMs; the gold set is.
"""

from __future__ import annotations

import json
import random
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from preflight.extract.labels import Span, bio_tags

OUT = Path("data/extract")

AIRPORTS = ["SFO", "JFK", "LAX", "ORD", "DEN", "ATL", "SEA", "BOS", "MIA", "DFW", "PHX",
            "IAH", "EWR", "MSP", "DTW", "LAS", "SLC", "SAN", "TWF", "EZF", "MPO", "BUR"]
RUNWAYS = ["09", "27", "10", "28", "01", "19", "13", "31", "36", "18", "04", "22", "16", "34",
           "28R", "28L", "22L", "22R", "04L", "04R", "25L", "25R", "16C", "34L", "01C", "15L",
           "33R", "08", "26", "12", "30"]
TAXIWAYS = ["A", "B", "C", "D", "E", "F", "G", "H", "K", "M", "Z", "A1", "B2", "C3", "K7",
            "AA", "BB", "NW", "S", "T"]
NAVAIDS = ["ILS", "LOC", "ILS/DME", "LOC/DME", "VOR", "VOR/DME", "VORTAC", "NDB", "DME",
           "GS", "TACAN", "RNAV", "LDA", "SDF", "LOM"]
LIGHTING = ["PAPI", "VASI", "MALSR", "MALSF", "SSALR", "ALSF-2", "REIL", "HIRL", "MIRL",
            "LIRL", "RCLL", "TDZL", "ALS", "ODALS", "RAIL", "TWY EDGE LGT", "APCH LGT"]
OBSTACLES = ["CRANE", "TOWER", "ANTENNA", "MAST", "OBST", "MOBILE CRANE", "CONSTRUCTION CRANE"]
AIRSPACE = ["TFR", "MOA", "RESTRICTED AREA R-{n}", "PROHIBITED AREA P-{n}", "DANGER AREA",
            "AIRSPACE", "CLASS B AIRSPACE", "WARNING AREA W-{n}"]
APRONS = ["APRON {x}", "APN {x}", "RAMP {x}", "STAND {n}", "GATE {x}", "NORTH APRON",
          "CARGO RAMP", "GA RAMP", "TERMINAL {x} APRON"]
SERVICES = ["ARFF", "FUEL", "CUSTOMS", "TWR", "ATIS", "AWOS", "ASOS", "APP", "GND", "CTAF",
            "JET A FUEL", "100LL FUEL", "DEICING SVC", "PPR SVC"]
CAUSES = ["WIP", "MAINT", "CONST", "SNOW REMOVAL", "RUBBER REMOVAL", "SFC REPAIR", "LGT MAINT",
          "EQUIPMENT FAILURE", "POWER FAILURE", "PAINTING", "MOWING", "CRANE OPS"]
STATES_CLOSED = ["CLSD", "CLOSED"]
STATES_US = ["U/S", "OTS", "UNSERVICEABLE", "OUT OF SERVICE", "NOT AVBL", "UNAVBL", "INOP"]
DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
SCHEDULES = ["DLY {h1}-{h2}", "SR-SS", "SS-SR", "MON-FRI {h1}-{h2}", "SAT SUN {h1}-{h2}",
             "EXC SAT SUN", "HJ", "HN", "DLY EXC MON {h1}-{h2}"]
# Natural-language noise a NOTAM body should never contain but a feed sometimes does — free
# text, web addresses, markup, chat-style prefixes. Labelled O throughout, so the model learns
# that prose is not a NOTAM even when it mentions runways. Deliberately none of the sentences
# in the red-team eval set (evals/safety/injections.jsonl); that set stays a test.
PROSE = [
    "Please confirm with operations before departure.", "This message is for planning only.",
    "See the attached document for details.", "Reply with a short summary of the above.",
    "The crew should review the latest bulletin.", "Note: times are local unless stated.",
    "For questions contact the duty manager.", "the runway will reopen when work is complete.",
    "Nothing further to report at this time.", "Weather looks fine for the afternoon.",
    "http://ops.example.org/status", "www.example.com/notices/latest", "<note>internal</note>",
    "[update] see below", "Status: pending review.", "Assistant: noted.", "User: thanks.",
    "System message: connection restored.", "## Summary", "- item one\n- item two",
    "ignore formatting issues in this text.", "This is a test of the notification system.",
    "the taxiway lights were replaced last week.", "Flights are operating normally today.",
    "Report any discrepancies to the airport authority.", "OK.", "Thanks, received.",
    "Do not reply to this address.", "Details to follow.", "n/a",
]

PROSE_UPPER = [
    "FOR INFORMATION ONLY.", "NO FURTHER ACTION REQUIRED.", "PLEASE ACKNOWLEDGE RECEIPT.",
    "THIS IS A DRILL.", "ALL PERSONNEL REPORT TO THE OPS OFFICE.", "CALL 555-0100 FOR DETAILS.",
    "REPORT ANY ISSUES TO THE DUTY OFFICER.", "THIS TEXT IS ADVISORY IN NATURE.",
    "OPERATOR: PLEASE CONFIRM.", "NOTE TO ALL USERS: READ CAREFULLY.", "END OF MESSAGE.",
    "REMARKS: NONE.", "STATUS UNCHANGED FROM PREVIOUS ISSUE.", "<<TAG>> ADVISORY <</TAG>>",
    "[MSG] SEE ATTACHED [/MSG]", "REF HTTPS://OPS.EXAMPLE.ORG/NOTICES", "SUMMARY FOLLOWS.",
    "N0TE: TH1S 1S A TEST.", "THE FOLLOWING IS FOR TRAINING PURPOSES.",
]


def _spaced(rng: random.Random) -> str:
    """Letter-spaced text — an obfuscation seen in feeds; never an entity."""
    pool = ["hello", "there", "please", "read", "this", "message", "carefully", "advisory",
            "notice", "attention", "operators", "review"]
    return " ".join(" ".join(w) for w in rng.sample(pool, k=rng.randrange(2, 5)))


def _asn_detail(rng: random.Random) -> str:
    """The FAA obstruction-study reference and coordinates an OBST NOTAM carries."""
    lat = f"{rng.randrange(25, 49):02d}{rng.randrange(0, 60):02d}{rng.randrange(0, 60):02d}N"
    lon = f"{rng.randrange(70, 125):03d}{rng.randrange(0, 60):02d}{rng.randrange(0, 60):02d}W"
    region = rng.choice(["AWP", "ASO", "ANE", "ACE", "AGL"])
    return f"(ASN 2026-{region}-{rng.randrange(100, 9999)}-OE) {lat}{lon}"


DISTRACTORS = [
    "ACFT USE CAUTION.", "PILOTS ARE ADVISED TO CTC TWR ON {f}.", "SEE AIP SUP {n}/26.",
    "ALL ACFT EXPECT DELAYS.", "REF AIP AD 2.", "CTC {ap} GND ON {f} FOR TAXI INSTRUCTIONS.",
    "OPR HRS UNCHANGED.", "PPR FOR ACFT ABV {w}FT WINGSPAN.", "BIRD ACTIVITY IN VICINITY OF AD.",
    "MEN AND EQUIPMENT ADJ TO MOVEMENT AREA.", "ACFT PARKING LIMITED.", "NIL.",
    "EXPECT ATC DELAYS DUE VOLUME.", "WX MINIMA APPLY.", "OBST LGT UNCHANGED.",
]


@dataclass
class Clause:
    text: str
    spans: list[Span]


class _Writer:
    """Builds a clause while recording spans relative to the clause start."""

    def __init__(self) -> None:
        self.text = ""
        self.spans: list[Span] = []

    def add(self, s: str) -> _Writer:
        self.text += s
        return self

    def ent(self, s: str, typ: str) -> _Writer:
        self.spans.append(Span(len(self.text), len(self.text) + len(s), typ))
        self.text += s
        return self

    def clause(self) -> Clause:
        return Clause(self.text, self.spans)


def _hhmm(rng: random.Random) -> str:
    return f"{rng.randrange(0, 24):02d}{rng.choice(['00', '15', '30', '45'])}"


def _schedule(rng: random.Random) -> str:
    h1, h2 = sorted((_hhmm(rng), _hhmm(rng)))
    return rng.choice(SCHEDULES).format(h1=h1, h2=h2)


def _window(rng: random.Random) -> str:
    """A US-domestic validity window: YYMMDDhhmm-YYMMDDhhmm[EST] | PERM | UFN."""
    m, d = rng.randrange(1, 13), rng.randrange(1, 24)
    start = f"26{m:02d}{d:02d}{_hhmm(rng)}"
    end = rng.choice([f"26{m:02d}{d + rng.randrange(0, 5):02d}{_hhmm(rng)}"
                      f"{rng.choice(['', '', 'EST'])}", "PERM", "UFN"])
    return f"{start}-{end}"


def _rwy(rng: random.Random) -> str:
    r = rng.choice(RUNWAYS)
    if rng.random() < 0.2:
        pair = {"09": "27", "10": "28", "01": "19", "13": "31", "18": "36", "04": "22",
                "16": "34", "28R": "10L", "28L": "10R", "22L": "04R", "04L": "22R"}
        if r in pair:
            return f"{r}/{pair[r]}"
    return r


def _c_runway(rng: random.Random) -> Clause:
    w = _Writer()
    w.ent(f"RWY {_rwy(rng)}", "RWY")
    kind = rng.random()
    if kind < 0.55:
        w.add(f" {rng.choice(STATES_CLOSED)}")
        if rng.random() < 0.6:
            w.add(f" DUE {rng.choice(CAUSES)}")
        if rng.random() < 0.3:
            w.add(" ").ent(_schedule(rng), "TIME")
    elif kind < 0.7:
        w.add(f" THLD DISPLACED {rng.randrange(200, 1500, 50)}FT")
    elif kind < 0.8:
        w.add(f" SFC COND {rng.choice(['WET', 'PATCHY ICE', 'COMPACTED SNOW', 'SLUSH'])}")
    elif kind < 0.9:
        w.add(f" LDA REDUCED TO {rng.randrange(4000, 9000, 100)}FT")
    else:
        w.add(" AVBL")
    return w.clause()


def _c_taxiway(rng: random.Random) -> Clause:
    w = _Writer()
    w.ent(f"TWY {rng.choice(TAXIWAYS)}", "TWY")
    if rng.random() < 0.35:
        w.add(" BTN ").ent(f"TWY {rng.choice(TAXIWAYS)}", "TWY").add(" AND ")
        w.ent(f"TWY {rng.choice(TAXIWAYS)}", "TWY")
    kind = rng.random()
    if kind < 0.7:
        w.add(f" {rng.choice(STATES_CLOSED)}")
        if rng.random() < 0.5:
            w.add(f" DUE {rng.choice(CAUSES)}")
    elif kind < 0.85:
        w.add(f" RESTRICTED TO ACFT WINGSPAN LESS THAN {rng.randrange(80, 215, 5)}FT")
    else:
        w.add(" CENTERLINE LGT U/S")
    return w.clause()


def _c_navaid(rng: random.Random) -> Clause:
    w = _Writer()
    nav = rng.choice(NAVAIDS)
    if nav in {"VOR", "VOR/DME", "VORTAC", "NDB", "TACAN", "DME", "LOM"} and rng.random() < 0.6:
        w.ent(f"{nav} {rng.choice(AIRPORTS)}", "NAVAID")
    else:
        w.ent(f"{nav} RWY {_rwy(rng)}", "NAVAID")
    w.add(f" {rng.choice(STATES_US)}")
    if rng.random() < 0.5:
        w.add(f" DUE {rng.choice(CAUSES)}")
    if rng.random() < 0.2:
        w.add(" ").ent(_schedule(rng), "TIME")
    return w.clause()


def _c_lighting(rng: random.Random) -> Clause:
    w = _Writer()
    lgt = rng.choice(LIGHTING)
    if lgt.startswith("TWY"):
        w.ent(f"TWY {rng.choice(TAXIWAYS)} EDGE LGT", "LIGHTING")
    elif rng.random() < 0.5:
        w.ent(f"{lgt} RWY {_rwy(rng)}", "LIGHTING")
    else:
        w.ent(f"RWY {_rwy(rng)} {lgt}", "LIGHTING")
    w.add(f" {rng.choice(STATES_US)}")
    if rng.random() < 0.3:
        w.add(f" DUE {rng.choice(CAUSES)}")
    return w.clause()


def _c_obstacle(rng: random.Random) -> Clause:
    w = _Writer()
    # Mention convention (matches the gold set): the obstacle words, not its height.
    if rng.random() < 0.35:
        w.ent(rng.choice(["OBST CRANE", "OBST TOWER", "OBST CRANE", "OBST ANTENNA"]), "OBSTACLE")
        w.add(f" {_asn_detail(rng)} ({rng.choice(['0.5', '0.8', '1.2', '2'])}NM "
              f"{rng.choice(DIRS)} APCH END ")
        w.ent(f"RWY {_rwy(rng)}", "RWY")
        h = rng.randrange(120, 500, 5)
        w.add(f") {h}FT ({h - rng.randrange(20, 90, 5)}FT AGL) "
              f"{rng.choice(['FLAGGED AND LGTD', 'LGTD', 'UNLGTD', 'FLAGGED'])}")
        return w.clause()
    w.ent(rng.choice(OBSTACLES), "OBSTACLE").add(f" {rng.randrange(50, 400, 10)}FT AGL")
    w.add(f" {rng.choice(['', 'APRX '])}{rng.choice(['0.5', '1', '1.5', '2', '3'])}NM "
          f"{rng.choice(DIRS)} OF ")
    w.ent(f"RWY {_rwy(rng)}", "RWY")
    w.add(rng.choice([" THLD", "", " APCH END"]))
    w.add(rng.choice([" LGTD", " UNLGTD", " LGT U/S", ""]))
    return w.clause()


def _c_airspace(rng: random.Random) -> Clause:
    w = _Writer()
    name = rng.choice(AIRSPACE).format(n=rng.randrange(2000, 6999))
    w.ent(name, "AIRSPACE")
    w.add(f" {rng.choice(['ACT', 'ACTIVE', 'IN EFFECT'])}")
    if rng.random() < 0.5:
        w.add(f" SFC-{rng.choice(['FL180', 'FL240', '10000FT', '5000FT AGL'])}")
    if rng.random() < 0.4:
        w.add(f" WI {rng.choice(['3', '5', '10', '30'])}NM RADIUS OF {rng.choice(AIRPORTS)}")
    if rng.random() < 0.3:
        w.add(" ").ent(_schedule(rng), "TIME")
    return w.clause()


def _c_apron(rng: random.Random) -> Clause:
    w = _Writer()
    w.ent(rng.choice(APRONS).format(x=rng.choice("ABCDEFG123"), n=rng.randrange(1, 60)), "APRON")
    w.add(f" {rng.choice(STATES_CLOSED)}")
    if rng.random() < 0.5:
        w.add(f" DUE {rng.choice(CAUSES)}")
    return w.clause()


def _c_service(rng: random.Random) -> Clause:
    w = _Writer()
    w.ent(rng.choice(SERVICES), "SERVICE")
    w.add(f" {rng.choice(['NOT AVBL', 'U/S', 'CLSD', 'UNAVBL', 'LIMITED'])}")
    if rng.random() < 0.4:
        w.add(" ").ent(_schedule(rng), "TIME")
    return w.clause()


def _c_prose(rng: random.Random) -> Clause:
    kind = rng.random()
    if kind < 0.15:
        return Clause(_spaced(rng), [])
    pool = PROSE_UPPER if kind < 0.5 else PROSE
    n = rng.choices([1, 2], weights=[75, 25])[0]
    return Clause(" ".join(rng.choice(pool) for _ in range(n)), [])


def _c_distractor(rng: random.Random) -> Clause:
    text = rng.choice(DISTRACTORS).format(
        f=f"1{rng.randrange(18, 36)}.{rng.choice(['0', '1', '2', '3', '5', '7', '8', '9'])}",
        n=rng.randrange(1, 40), ap=rng.choice(AIRPORTS), w=rng.randrange(100, 215, 5))
    return Clause(text.rstrip("."), [])


_GENERATORS = [_c_runway, _c_taxiway, _c_navaid, _c_lighting, _c_obstacle, _c_airspace,
               _c_apron, _c_service]
_WEIGHTS = [26, 16, 14, 14, 8, 6, 8, 8]


def make_body(rng: random.Random) -> tuple[str, list[Span]]:
    """One NOTAM body: 1–4 clauses, optional distractor, ICAO or US-domestic framing."""
    n = rng.choices([1, 2, 3, 4], weights=[45, 32, 16, 7])[0]
    clauses = [rng.choices(_GENERATORS, weights=_WEIGHTS)[0](rng) for _ in range(n)]
    if rng.random() < 0.35:
        clauses.insert(rng.randrange(0, len(clauses) + 1), _c_distractor(rng))
    if rng.random() < 0.4:
        clauses.insert(rng.randrange(0, len(clauses) + 1), _c_prose(rng))
    text, spans = "", list[Span]()
    us_style = rng.random() < 0.3
    if us_style:
        ap = rng.choice(AIRPORTS)
        # "!SFO 09/142 SFO …": the FAA domestic header — accountability, number, location.
        text = (f"!{ap} {rng.randrange(1, 13):02d}/{rng.randrange(1, 999):03d} {ap} "
                if rng.random() < 0.6 else f"{ap} ")
    for i, c in enumerate(clauses):
        if i:
            text += rng.choice([". ", ". ", ".\n", " "]) if not us_style else " "
        spans.extend(Span(s.start + len(text), s.end + len(text), s.type) for s in c.spans)
        text += c.text
    if us_style:
        text += " "
        win = _window(rng)
        spans.append(Span(len(text), len(text) + len(win), "TIME"))
        text += win
    elif rng.random() < 0.7:
        text += "."
    if rng.random() < 0.15:
        text = text.lower() if rng.random() < 0.3 else text
    return text, spans


def generate(n: int, *, seed: int = 20260918) -> Iterator[dict[str, object]]:
    rng = random.Random(seed)
    for i in range(n):
        text, spans = make_body(rng)
        tokens, tags = bio_tags(text, spans)
        yield {"id": f"syn-{seed}-{i:06d}", "text": text, "tokens": tokens, "tags": tags,
               "spans": [[s.start, s.end, s.type] for s in spans]}


def write_dataset(n: int, out: Path = OUT, *, seed: int = 20260918,
                  val_fraction: float = 0.1) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    rows = list(generate(n, seed=seed))
    n_val = int(len(rows) * val_fraction)
    for name, part in (("train", rows[n_val:]), ("val", rows[:n_val])):
        with (out / f"{name}.jsonl").open("w") as f:
            for r in part:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"train": len(rows) - n_val, "val": n_val}
