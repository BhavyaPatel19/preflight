"""HTTP surface. Pure endpoints run anywhere; the streaming briefing needs the database."""

import json
import warnings

import pytest
from fastapi.testclient import TestClient

from preflight.api.main import app

warnings.filterwarnings("ignore", message=".*httpx.*starlette.testclient.*")


@pytest.fixture(scope="module")
def client():
    # Keep the suite fast: don't load the retrieval models for API tests.
    import preflight.api.main as m

    original = m.load_retriever
    m.load_retriever = lambda: None
    try:
        with TestClient(app) as c:
            yield c
    finally:
        m.load_retriever = original


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200 and r.json()["status"] == "ok"


def test_index_serves_the_briefing_ui(client):
    r = client.get("/")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    body = r.text
    assert "<title>Preflight</title>" in body
    assert "NOT FOR OPERATIONAL USE" in body                 # the scope note is on the page
    assert 'new EventSource("/brief/stream?' in body          # consumes the GET stream


def test_decode_endpoint(client):
    r = client.post("/decode", json={"text": "!SFO 09/142 SFO RWY 28R CLSD 2609102330-2609110700"})
    assert r.status_code == 200 and r.json()["hazard_class"] == "runway_closure"
    assert client.post("/decode", json={"text": "not a notam"}).status_code == 422


def test_stream_get_validates_icao(client):
    r = client.get("/brief/stream", params={"departure": "SFO", "destination": "KJFK",
                                            "off_block": "2026-09-12T14:00:00Z"})
    assert r.status_code == 422


@pytest.mark.db
def test_stream_get_emits_start_findings_done(client):
    with client.stream("GET", "/brief/stream", params={
        "departure": "KSFO", "destination": "KJFK", "alternates": "KBOS",
        "off_block": "2026-09-12T14:00:00Z", "precedent": "false",
    }) as r:
        assert r.status_code == 200
        lines = [ln for ln in r.iter_lines() if ln]
    events = [ln.split(": ", 1)[1] for ln in lines if ln.startswith("event:")]
    assert events[0] == "start" and events[-1] == "done"
    done = json.loads([ln for ln in lines if ln.startswith("data:")][-1].split(": ", 1)[1])
    assert {"findings", "abstentions", "sources_considered", "latency_ms"} <= set(done)
    assert done["findings"] == events.count("finding")
    assert done["abstentions"] == events.count("abstention")
