"""Decode a raw METAR string into the same ``Metar`` record aviationweather.gov's JSON gives.

Live weather arrives pre-parsed from aviationweather.gov; historical weather from
the Iowa State ASOS archive arrives as the raw report only. The briefing's rules
read ``flight_category``, wind, gust, visibility and ceiling, so those are decoded
here from the standard groups — nothing exotic (no RVR, no runway state groups),
and anything unrecognised is left ``None`` rather than guessed.
"""

from __future__ import annotations

import re
from datetime import datetime

from preflight.sources.aviationweather import Metar

_WIND = re.compile(r"^(?P<dir>\d{3}|VRB)(?P<spd>\d{2,3})(?:G(?P<gst>\d{2,3}))?(?P<unit>KT|MPS)$")
_VIS_SM = re.compile(r"^(?P<m>M)?(?P<p>P)?(?P<num>\d{1,2}(?:/\d{1,2})?)SM$")
_VIS_FRAC_TAIL = re.compile(r"^(?P<m>M)?(?P<num>\d{1,2}/\d{1,2})SM$")
_CLOUD = re.compile(r"^(?P<cov>FEW|SCT|BKN|OVC|VV)(?P<hgt>\d{3})(?:CB|TCU)?$")
_TEMP = re.compile(r"^(?P<t>M?\d{2})/(?P<d>M?\d{2})?$")
_ALT = re.compile(r"^A(?P<inhg>\d{4})$")
_QNH = re.compile(r"^Q(?P<hpa>\d{4})$")
_WX = re.compile(
    r"^[+-]?(?:VC)?(?:MI|PR|BC|DR|BL|SH|TS|FZ)?"
    r"(?:DZ|RA|SN|SG|IC|PL|GR|GS|UP|BR|FG|FU|VA|DU|SA|HZ|PY|PO|SQ|FC|SS|DS){1,3}$"
)


def _frac(text: str) -> float:
    if "/" in text:
        a, b = text.split("/")
        return int(a) / int(b)
    return float(text)


def flight_category(visibility_sm: float | None, ceiling_ft: int | None) -> str | None:
    """FAA categories: LIFR < 500 ft or < 1 SM; IFR < 1000 ft or < 3 SM; MVFR ≤ 3000 ft or
    ≤ 5 SM; otherwise VFR. Unknown when neither element was reported."""
    if visibility_sm is None and ceiling_ft is None:
        return None
    vis = visibility_sm if visibility_sm is not None else 99.0
    ceil = ceiling_ft if ceiling_ft is not None else 99_999
    if ceil < 500 or vis < 1:
        return "LIFR"
    if ceil < 1000 or vis < 3:
        return "IFR"
    if ceil <= 3000 or vis <= 5:
        return "MVFR"
    return "VFR"


def parse_metar(raw: str, *, icao: str, observed_at: datetime) -> Metar:
    """Decode the standard groups of one METAR. Remarks (after ``RMK``) are ignored."""
    body = raw.split(" RMK", 1)[0].split(" TEMPO", 1)[0].split(" BECMG", 1)[0]
    tokens = body.split()
    wind_dir = wind_kt = gust_kt = None
    vis: float | None = None
    ceiling: int | None = None
    temp = dew = alt_hpa = None
    wx: list[str] = []
    pending_int: int | None = None          # "2" of "2 1/2SM"

    for tok in tokens[1:]:                  # tokens[0] is the station
        if (m := _WIND.match(tok)):
            wind_dir = None if m["dir"] == "VRB" else int(m["dir"])
            spd, gst = int(m["spd"]), (int(m["gst"]) if m["gst"] else None)
            if m["unit"] == "MPS":
                spd = round(spd * 1.94384)
                gst = round(gst * 1.94384) if gst else None
            wind_kt, gust_kt = spd, gst
            continue
        if tok.isdigit() and len(tok) <= 2 and vis is None:
            pending_int = int(tok)          # whole-mile part of a mixed number
            continue
        if tok.isdigit() and len(tok) == 4 and vis is None and wind_kt is not None:
            vis = 6.2 if tok == "9999" else round(int(tok) / 1609.34, 2)   # metres (ICAO form)
            continue
        if (m := _VIS_SM.match(tok)):
            value = _frac(m["num"]) + (pending_int or 0)
            pending_int = None
            vis = 0.0 if m["m"] and value <= 0.25 else value     # M1/4SM: "less than"
            continue
        if (m := _CLOUD.match(tok)):
            if m["cov"] in {"BKN", "OVC", "VV"}:
                h = int(m["hgt"]) * 100
                ceiling = h if ceiling is None else min(ceiling, h)
            continue
        if tok in {"CLR", "SKC", "NSC", "NCD", "CAVOK"}:
            if tok == "CAVOK" and vis is None:
                vis = 6.2
            continue
        if (m := _TEMP.match(tok)):
            temp = float(m["t"].replace("M", "-"))
            dew = float(m["d"].replace("M", "-")) if m["d"] else None
            continue
        if (m := _ALT.match(tok)):
            alt_hpa = round(int(m["inhg"]) / 100 * 33.8639, 1)
            continue
        if (m := _QNH.match(tok)):
            alt_hpa = float(m["hpa"])
            continue
        if _WX.match(tok):
            wx.append(tok)

    return Metar(
        icao=icao, observed_at=observed_at, raw=raw.strip(),
        flight_category=flight_category(vis, ceiling),
        wind_dir=wind_dir, wind_kt=wind_kt, gust_kt=gust_kt, visibility_sm=vis,
        temp_c=temp, dewpoint_c=dew, altimeter_hpa=alt_hpa,
        wx=" ".join(wx) or None, ceiling_ft=ceiling,
    )
