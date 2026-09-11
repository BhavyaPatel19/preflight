from preflight.decode.qcode import CONDITION, SUBJECT, decode_qcode


def test_decodes_runway_closed():
    q = decode_qcode("QMRLC")
    assert q is not None
    assert q.subject_text == "runway"
    assert q.condition_text == "closed"
    assert q.hazard_class == "runway_closure"
    assert q.is_degraded
    assert q.severity == "HIGH"


def test_ils_unserviceable_is_high():
    q = decode_qcode("QICAS")
    assert q is not None and q.severity == "HIGH" and q.hazard_class == "approach_aids"


def test_taxiway_closed_is_not_critical():
    q = decode_qcode("QMXLC")
    assert q is not None and q.severity == "MEDIUM" and q.hazard_class == "taxiway"


def test_operational_condition_is_info():
    q = decode_qcode("QMRAO")  # runway operational
    assert q is not None and not q.is_degraded and q.severity == "INFO"


def test_lowercase_and_whitespace_tolerated():
    assert decode_qcode("  qmrlc ") == decode_qcode("QMRLC")


def test_malformed_returns_none_rather_than_raising():
    for bad in ["", "XX", "QMRL", "QMRLCC", "Q1RLC", None]:  # type: ignore[list-item]
        assert decode_qcode(bad) is None  # type: ignore[arg-type]


def test_unknown_but_wellformed_code_degrades_gracefully():
    q = decode_qcode("QZZLC")  # unknown subject, known condition
    assert q is not None and "unknown subject" in q.subject_text and q.condition_text == "closed"


def test_taxonomy_is_populated():
    assert len(SUBJECT) > 140 and len(CONDITION) > 75
