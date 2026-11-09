"""Decode a TAF into time-bounded forecast periods.

A TAF is a header (station, issue time, validity) followed by change groups:

* ``FM ddhhmm`` — from that time the forecast is wholly replaced (a new prevailing period);
* ``BECMG dd hh/dd hh`` — a lasting change: only the elements it lists change, the rest carry;
* ``TEMPO dd hh/dd hh`` — temporary fluctuations within the window, lasting under an hour each;
* ``PROB30`` / ``PROB40`` (optionally ``PROB30 TEMPO``) — a 30 / 40 % chance of the conditions.

Each period keeps the verbatim text of its group, because a briefing that cites a forecast has to
quote the words the forecaster wrote, not a paraphrase. Times are resolved against the issue time
so a TAF issued on the 31st and valid into the 1st lands in the right month.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

from preflight.sources.metar_text import _CLOUD, _VIS_SM, _WIND, _WX, _frac, flight_category


class TafParseError(ValueError):
    """The text does not have the shape of a TAF header."""


@dataclass(frozen=True)
class TafPeriod:
    kind: str                       # BASE | FM | BECMG | TEMPO | PROB
    start: datetime
    end: datetime
    text: str                       # the verbatim group, as the forecaster wrote it
    probability: int | None = None  # 30 / 40 for PROB groups
    wind_kt: int | None = None
    gust_kt: int | None = None
    visibility_sm: float | None = None
    ceiling_ft: int | None = None
    wx: tuple[str, ...] = field(default=())

    @property
    def flight_category(self) -> str | None:
        return flight_category(self.visibility_sm, self.ceiling_ft)

    @property
    def temporary(self) -> bool:
        return self.kind in {"TEMPO", "PROB"}

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return self.start < end and self.end > start


_HEADER = re.compile(
    r"^(?:TAF\s+)?(?:(?:AMD|COR)\s+)?(?P<icao>[A-Z0-9]{4})\s+(?P<issued>\d{6})Z\s+"
    r"(?:(?P<vfrom>\d{4})/(?P<vto>\d{4})\s*)?(?P<body>.*)$",
    re.S,
)
# A change group starts at one of these tokens; the lookahead keeps the token with its group.
_SPLIT = re.compile(r"\s+(?=FM\d{6}\b|BECMG\b|TEMPO\b|PROB\d{2}\b)")
_SPAN = re.compile(r"^(\d{4})/(\d{4})$")


def _resolve(day: int, hour: int, minute: int, ref: datetime) -> datetime:
    """The datetime with this day-of-month nearest to ``ref`` (TAFs span at most ~30 h)."""
    best: datetime | None = None
    for months in (-1, 0, 1):
        y, m = ref.year, ref.month + months
        if m == 0:
            y, m = y - 1, 12
        elif m == 13:
            y, m = y + 1, 1
        try:
            base = datetime(y, m, day, tzinfo=UTC)
        except ValueError:          # e.g. the 31st of a 30-day month
            continue
        cand = base + timedelta(hours=hour, minutes=minute)   # hour 24 rolls to the next day
        if best is None or abs(cand - ref) < abs(best - ref):
            best = cand
    if best is None:
        raise TafParseError(f"no month has day {day}")
    return best


def _ddhh(token: str, ref: datetime) -> datetime:
    return _resolve(int(token[:2]), int(token[2:4]), 0, ref)


def _decode(tokens: list[str]) -> dict[str, object]:
    """Weather elements of one group; only the ones present appear in the result."""
    out: dict[str, object] = {}
    wx: list[str] = []
    pending_int: int | None = None
    ceiling: int | None = None
    saw_sky = False
    for tok in tokens:
        if (m := _WIND.match(tok)):
            spd, gst = int(m["spd"]), (int(m["gst"]) if m["gst"] else None)
            if m["unit"] == "MPS":
                spd = round(spd * 1.94384)
                gst = round(gst * 1.94384) if gst else None
            out["wind_kt"], out["gust_kt"] = spd, gst
        elif tok.isdigit() and len(tok) <= 2 and "visibility_sm" not in out:
            pending_int = int(tok)
        elif tok.isdigit() and len(tok) == 4 and "visibility_sm" not in out:
            out["visibility_sm"] = 6.2 if tok == "9999" else round(int(tok) / 1609.34, 2)
        elif (m := _VIS_SM.match(tok)):
            value = _frac(m["num"]) + (pending_int or 0)
            pending_int = None
            out["visibility_sm"] = 6.2 if m["p"] else (0.0 if m["m"] and value <= 0.25 else value)
        elif (m := _CLOUD.match(tok)):
            saw_sky = True
            if m["cov"] in {"BKN", "OVC", "VV"}:
                h = int(m["hgt"]) * 100
                ceiling = h if ceiling is None else min(ceiling, h)
        elif tok in {"SKC", "CLR", "NSC", "CAVOK"}:
            saw_sky = True
            if tok == "CAVOK":
                out["visibility_sm"] = 6.2
        elif tok == "NSW":
            out["wx"] = ()
        elif _WX.match(tok):
            wx.append(tok)
    if saw_sky:
        out["ceiling_ft"] = ceiling          # None = sky reported with no ceiling
    if wx:
        out["wx"] = tuple(wx)
    return out


def taf_header(raw: str, *, ref: datetime) -> tuple[str, datetime, datetime, datetime]:
    """(station, issued_at, valid_from, valid_to) of a TAF, resolved against ``ref`` — a time
    within a day or so of issuance, such as the end of the window the TAF was fetched for."""
    text = " ".join(raw.replace("=", " ").split())
    m = _HEADER.match(text)
    if not m or not m["vfrom"]:
        raise TafParseError(f"no TAF header with a validity group: {raw[:40]!r}")
    ref = ref.astimezone(UTC)
    iss = m["issued"]
    issued = _resolve(int(iss[:2]), int(iss[2:4]), int(iss[4:6]), ref)
    return m["icao"], issued, _ddhh(m["vfrom"], issued), _ddhh(m["vto"], issued)


def parse_taf(
    raw: str, *, issued_at: datetime,
    valid_from: datetime | None = None, valid_to: datetime | None = None,
) -> list[TafPeriod]:
    """Every period of the TAF, in order. Raises :class:`TafParseError` on a malformed header.

    The validity group in the text wins; ``valid_from`` / ``valid_to`` (as a feed reports them
    beside the text) are the fallback for text that arrives without one.
    """
    text = " ".join(raw.replace("=", " ").split())
    m = _HEADER.match(text)
    if not m:
        raise TafParseError(f"not a TAF: {raw[:40]!r}")
    ref = issued_at.astimezone(UTC)
    if m["vfrom"]:
        valid_from, valid_to = _ddhh(m["vfrom"], ref), _ddhh(m["vto"], ref)
    elif valid_from is None or valid_to is None:
        raise TafParseError("TAF has no validity group and none was given")
    else:
        valid_from, valid_to = valid_from.astimezone(UTC), valid_to.astimezone(UTC)
    if valid_to <= valid_from:
        raise TafParseError(f"validity {m['vfrom']}/{m['vto']} does not run forward")

    groups = _SPLIT.split(m["body"].strip()) if m["body"].strip() else []
    if not groups:
        raise TafParseError("TAF has no forecast body")

    head = f"{m['icao']} {m['issued']}Z" + (f" {m['vfrom']}/{m['vto']}" if m["vfrom"] else "")
    prevailing: list[TafPeriod] = [
        TafPeriod(kind="BASE", start=valid_from, end=valid_to, text=f"{head} {groups[0]}",
                  **_decode(groups[0].split()))  # type: ignore[arg-type]
    ]
    temporary: list[TafPeriod] = []

    for g in groups[1:]:
        toks = g.split()
        lead = toks[0]
        if lead.startswith("FM"):
            start = _resolve(int(lead[2:4]), int(lead[4:6]), int(lead[6:8]), ref)
            prevailing[-1] = replace(prevailing[-1], end=start)
            prevailing.append(TafPeriod(kind="FM", start=start, end=valid_to, text=g,
                                        **_decode(toks[1:])))  # type: ignore[arg-type]
            continue
        prob: int | None = None
        rest = toks[1:]
        if lead.startswith("PROB"):
            prob = int(lead[4:])
            if rest and rest[0] == "TEMPO":
                rest = rest[1:]
        if not rest or not (span := _SPAN.match(rest[0])):
            continue                                    # a group without a time span: skip it
        start, end = _ddhh(span[1], ref), _ddhh(span[2], ref)
        elements = _decode(rest[1:])
        if lead == "BECMG":
            # A lasting change: the listed elements change from the start of the window and
            # persist; everything else carries over from the prevailing period.
            cur = prevailing[-1]
            prevailing[-1] = replace(cur, end=start)
            prevailing.append(replace(cur, kind="BECMG", start=start, end=cur.end, text=g,
                                      **elements))  # type: ignore[arg-type]
        else:
            temporary.append(TafPeriod(kind="PROB" if prob else "TEMPO", start=start, end=end,
                                       text=g, probability=prob,
                                       **elements))  # type: ignore[arg-type]

    return [p for p in prevailing if p.end > p.start] + temporary
