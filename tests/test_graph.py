"""The briefing graph: ordering, skipping by availability and options, and resumption."""

from contextlib import nullcontext
from datetime import UTC, datetime

import pytest

from preflight.graph import Deps, Options, build_graph, run_briefing
from preflight.schemas import FlightRequest

T0 = datetime(2026, 9, 11, 2, 30, tzinfo=UTC)
REQ = FlightRequest(departure="KSFO", destination="KJFK", off_block=T0)


class Retriever:
    def search(self, conn, q, **kw):
        return []


class Verifier:
    name = "fake-nli"

    def entailment(self, pairs):
        return [0.9 for _ in pairs]


class LLM:
    name = "fake-llm"

    def __init__(self, fail_times=0):
        self.fail_times = fail_times
        self.calls = 0

    def complete_json(self, system, user, schema, *, max_tokens=400):
        self.calls += 1
        if self.fail_times:
            self.fail_times -= 1
            from preflight.llm import LLMUnavailable
            raise LLMUnavailable("down")
        if "sentences" in str(schema):
            return {"sentences": ["Runway 28R is closed."]}
        return {"query": "a rewritten precedent query"}


def _deps(db, **kw):
    return Deps(connect=lambda: nullcontext(db), now=lambda: T0, **kw)


@pytest.mark.db
def test_all_stages_run_in_order(db):
    g = build_graph(_deps(db, retriever=Retriever(), verifier=Verifier(), llm=LLM()))
    b, state = run_briefing(g, REQ, thread_id="t-all")
    stages = [t.split(":")[0] for t in state["trace"]]
    assert stages == ["gather", "precedent", "verify", "narrate"]
    assert b.trace_id == "t-all" and b.request.departure == "KSFO"
    assert state["narrative_stats"] is not None


@pytest.mark.db
def test_stages_skip_when_unavailable(db):
    g = build_graph(_deps(db))                                   # no retriever/verifier/llm
    _, state = run_briefing(g, REQ, thread_id="t-none")
    assert [t.split(":")[0] for t in state["trace"]] == ["gather"]


@pytest.mark.db
def test_options_turn_stages_off(db):
    g = build_graph(_deps(db, retriever=Retriever(), verifier=Verifier(), llm=LLM()))
    opts: Options = {"precedent": False, "narrative": False}
    _, state = run_briefing(g, REQ, options=opts, thread_id="t-opts")
    assert [t.split(":")[0] for t in state["trace"]] == ["gather", "verify"]


@pytest.mark.db
def test_narrative_without_verifier_is_not_run(db):
    g = build_graph(_deps(db, llm=LLM()))
    _, state = run_briefing(g, REQ, thread_id="t-noverify")
    assert [t.split(":")[0] for t in state["trace"]] == ["gather"]


@pytest.mark.db
def test_resume_after_a_failed_node_does_not_redo_earlier_stages(db):
    """Narrate raises on the first attempt; the second invoke resumes from the checkpoint."""
    llm = LLM(fail_times=1)
    deps = _deps(db, retriever=Retriever(), verifier=Verifier(), llm=llm)
    calls = {"gather": 0}
    original = deps.connect

    def counting_connect():
        calls["gather"] += 1
        return original()

    deps.connect = counting_connect
    g = build_graph(deps)

    # with_narrative swallows LLMUnavailable, so make the node itself blow up once instead
    import preflight.graph as G
    real = G.with_narrative
    state_of = {"n": 0}

    def flaky(b, llm_, verifier):
        state_of["n"] += 1
        if state_of["n"] == 1:
            raise RuntimeError("narrative backend exploded")
        return real(b, llm_, verifier)

    G.with_narrative = flaky
    try:
        with pytest.raises(RuntimeError):
            run_briefing(g, REQ, thread_id="t-resume")
        gather_calls_after_failure = calls["gather"]
        b, state = run_briefing(g, REQ, thread_id="t-resume")           # resume
    finally:
        G.with_narrative = real
    assert [t.split(":")[0] for t in state["trace"]] == ["gather", "precedent", "verify", "narrate"]
    # connect() is used by gather and precedent; neither ran again on resume
    assert calls["gather"] == gather_calls_after_failure
    assert b.trace_id == "t-resume"
