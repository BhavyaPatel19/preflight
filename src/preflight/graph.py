"""The briefing as a graph.

Each stage that already exists — gather (the deterministic core), precedent,
verify, narrate — becomes a node over one typed state, wired as a LangGraph
``StateGraph``. What the graph adds over calling the functions in a row:

* **Durable progress.** With the Postgres checkpointer, state is saved after
  every node. If the narrative model is down mid-run, the run fails at
  ``narrate`` with gather/precedent/verify already checkpointed; invoking the
  same ``thread_id`` again resumes from there instead of redoing the whole
  briefing.
* **Explicit control flow.** Which stages run is a property of the request
  (``options``) and of what is available (``deps``), decided at the edges,
  not buried in call sites.
* **One place to trace.** Every node records what it did in ``trace`` and how
  long it took in ``timings``; the briefing carries ``trace_id`` = ``thread_id``.

The nodes are thin. All behaviour lives in the modules they call, which keep
their own tests; the graph tests cover ordering, skipping, and resumption.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from preflight.brief.core import build_briefing
from preflight.brief.narrate import with_narrative
from preflight.brief.precedent import with_precedent
from preflight.schemas import Briefing, FlightRequest
from preflight.verify.ground import with_verification


class Options(TypedDict, total=False):
    precedent: bool
    verify: bool
    narrative: bool


class BriefingState(TypedDict, total=False):
    request: dict[str, Any]           # FlightRequest, JSON form (checkpoint-safe)
    options: Options
    briefing: dict[str, Any]          # Briefing, JSON form
    trace: list[str]
    timings: dict[str, int]           # node name → wall milliseconds
    narrative_stats: dict[str, Any] | None


@dataclass
class Deps:
    """What the nodes need. ``None`` for anything unavailable; edges skip accordingly."""

    connect: Callable[[], Any]                     # context manager yielding a Connection
    retriever: Any = None
    verifier: Any = None
    llm: Any = None
    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))


def _briefing(state: BriefingState) -> Briefing:
    return Briefing.model_validate(state["briefing"])


def _put(b: Briefing, note: str, state: BriefingState) -> BriefingState:
    return {"briefing": b.model_dump(mode="json"), "trace": [*state.get("trace", []), note]}


def _timed(name: str, node: Callable[[BriefingState], BriefingState]) -> Any:
    """Record the node's wall time in ``timings`` (state keys are replaced, so merge)."""
    def run(state: BriefingState) -> BriefingState:
        t0 = perf_counter()
        out = node(state)
        out["timings"] = {**state.get("timings", {}), name: int((perf_counter() - t0) * 1000)}
        return out
    return run


def build_graph(deps: Deps, checkpointer: BaseCheckpointSaver[Any] | None = None) -> Any:
    def gather(state: BriefingState) -> BriefingState:
        req = FlightRequest.model_validate(state["request"])
        with deps.connect() as conn:
            b = build_briefing(conn, req, now=deps.now())
        return _put(b, f"gather: {len(b.findings)} findings, {len(b.abstentions)} abstentions",
                    state)

    def precedent(state: BriefingState) -> BriefingState:
        b = _briefing(state)
        with deps.connect() as conn:
            b = with_precedent(conn, b, deps.retriever, llm=deps.llm)
        n = sum(1 for f in b.findings for c in f.claims
                if any(cit.kind in {"asrs", "ntsb"} for cit in c.citations))
        return _put(b, f"precedent: {n} findings with prior reports", state)

    def verify(state: BriefingState) -> BriefingState:
        b = with_verification(_briefing(state), deps.verifier)
        checked = [c for f in b.findings for c in f.claims if c.verified is not None]
        failed = sum(1 for c in checked if c.verified is False)
        return _put(b, f"verify: {len(checked)} claims checked, {failed} unsupported", state)

    def narrate(state: BriefingState) -> BriefingState:
        b, stats = with_narrative(_briefing(state), deps.llm, deps.verifier)
        out = _put(b, "narrate: " + (f"{stats.generated} sentences, {stats.dropped} dropped"
                                     if stats else "skipped"), state)
        out["narrative_stats"] = (
            {"model": stats.model, "generated": stats.generated, "kept": stats.kept,
             "dropped": stats.dropped, "failed_calls": stats.failed_calls} if stats else None)
        return out

    def wants(state: BriefingState, key: str, default: bool = True) -> bool:
        return bool(state.get("options", {}).get(key, default))

    def after_gather(state: BriefingState) -> str:
        if wants(state, "precedent") and deps.retriever is not None:
            return "precedent"
        return after_precedent(state)

    def after_precedent(state: BriefingState) -> str:
        if (wants(state, "verify") or wants(state, "narrative")) and deps.verifier is not None:
            return "verify"
        return END

    def after_verify(state: BriefingState) -> str:
        if wants(state, "narrative") and deps.llm is not None:
            return "narrate"
        return END

    g: StateGraph[BriefingState] = StateGraph(BriefingState)
    g.add_node("gather", _timed("gather", gather))
    g.add_node("precedent", _timed("precedent", precedent))
    g.add_node("verify", _timed("verify", verify))
    g.add_node("narrate", _timed("narrate", narrate))
    g.add_edge(START, "gather")
    g.add_conditional_edges("gather", after_gather, ["precedent", "verify", END])
    g.add_conditional_edges("precedent", after_precedent, ["verify", END])
    g.add_conditional_edges("verify", after_verify, ["narrate", END])
    g.add_edge("narrate", END)
    return g.compile(checkpointer=checkpointer or InMemorySaver())


def run_briefing(
    graph: Any, req: FlightRequest, *, options: Options | None = None,
    thread_id: str | None = None,
) -> tuple[Briefing, BriefingState]:
    """Run (or resume) one briefing. The thread id is the briefing's trace id."""
    thread_id = thread_id or uuid.uuid4().hex[:12]
    config = {"configurable": {"thread_id": thread_id}}
    initial: BriefingState = {
        "request": req.model_dump(mode="json"), "options": options or {}, "trace": [],
        "timings": {},
    }
    # Resuming: a checkpoint for this thread means gather already ran; pass no new input.
    existing = graph.get_state(config)
    payload = None if existing and existing.values.get("briefing") else initial
    state: BriefingState = graph.invoke(payload, config)
    b = _briefing(state).model_copy(update={"trace_id": thread_id})
    return b, state


@contextmanager
def postgres_checkpointer(conninfo: str) -> Iterator[BaseCheckpointSaver[Any]]:
    """LangGraph's own tables in our database (``checkpoints*``); created on first use."""
    from langgraph.checkpoint.postgres import PostgresSaver

    with PostgresSaver.from_conn_string(conninfo) as saver:
        saver.setup()
        yield saver


def pooled_connect(get_pool: Callable[[], Any]) -> Callable[[], Any]:
    def connect() -> Any:
        return get_pool().connection()
    return connect

