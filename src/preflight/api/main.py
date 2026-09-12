"""HTTP surface.

``/decode`` and ``/brief`` are real. ``/brief/stream`` emits the same briefing
section by section over SSE so a client can render progressively; the agent
layer (Sprint 4) slots in behind the same events without changing the wire.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from preflight import __version__
from preflight.brief import build_briefing
from preflight.db import close_pool, get_pool
from preflight.decode.notam import NotamParseError, parse_notam
from preflight.schemas import Briefing, FlightRequest, NotamRecord


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield
    close_pool()


app = FastAPI(
    title="Preflight",
    version=__version__,
    description="Agentic route-risk briefing. Research system — not for operational use.",
    lifespan=_lifespan,
)


class DecodeRequest(BaseModel):
    text: str = Field(min_length=1, description="Raw NOTAM, ICAO or US domestic format")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/decode", response_model=NotamRecord)
async def decode(req: DecodeRequest) -> NotamRecord:
    try:
        return parse_notam(req.text)
    except NotamParseError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _build(req: FlightRequest) -> Briefing:
    with get_pool().connection() as conn:
        return build_briefing(conn, req)


@app.post("/brief", response_model=Briefing)
async def brief(req: FlightRequest) -> Briefing:
    return await asyncio.to_thread(_build, req)


async def _brief_events(req: FlightRequest) -> AsyncIterator[dict[str, str]]:
    yield {"event": "start", "data": json.dumps({
        "departure": req.departure, "destination": req.destination,
        "alternates": list(req.alternates),
    })}
    b = await asyncio.to_thread(_build, req)
    for f in b.ranked():
        yield {"event": "finding", "data": f.model_dump_json()}
    for a in b.abstentions:
        yield {"event": "abstention", "data": a.model_dump_json()}
    yield {"event": "done", "data": json.dumps({
        "findings": len(b.findings), "abstentions": len(b.abstentions),
        "sources_considered": b.sources_considered, "latency_ms": b.latency_ms,
        "generated_at": b.generated_at.isoformat(),
    })}


@app.post("/brief/stream")
async def brief_stream(req: FlightRequest) -> EventSourceResponse:
    return EventSourceResponse(_brief_events(req))
