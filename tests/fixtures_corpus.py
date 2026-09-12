"""Synthetic ops notes for retrieval tests. Written for tests — NOT real ASRS reports."""

SYNTHETIC_NOTES: dict[str, tuple[str | None, str]] = {
    "syn-001": (
        "KZZY",
        "Night arrival with 28L closed for construction. Crew briefed 28R but the approach "
        "lighting configuration with the parallel dark led to a late realization we were "
        "aligned with taxiway C. Go-around initiated at 300 ft. Contributing: fatigue, unusual "
        "lighting, NOTAM buried in a long package.",
    ),
    "syn-002": (
        "KZZY",
        "Low visibility taxi. Taxiway B closed between A and F per NOTAM; ground issued a "
        "reroute via taxiway F which we initially missed. Stopped, confirmed with ground, no "
        "conflict. Recommend highlighting taxiway closures on the airport diagram.",
    ),
    "syn-003": (
        "KZZX",
        "ILS 22L out of service for maintenance during our arrival. Flew the RNAV approach "
        "instead. Autopilot mode confusion at glidepath intercept; corrected by hand-flying. "
        "Weather was VFR so no safety margin issue, but a briefing item we nearly missed.",
    ),
    "syn-004": (
        None,
        "Bird strike on departure roll at rotation speed. Continued takeoff, returned for "
        "inspection. No damage found. Reporting because flock activity had been noted in an "
        "earlier PIREP that did not reach our dispatch package.",
    ),
    "syn-005": (
        "KZZW",
        "Runway 4R/22L closed overnight for lighting work. Landed 33L with a crosswind near "
        "limits. Suggest earlier notification of the closure so alternate runway performance "
        "can be planned at dispatch rather than on descent.",
    ),
}
