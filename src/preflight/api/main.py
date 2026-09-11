"""HTTP surface.

``/decode`` is real today. ``/brief`` streams a stub so the SSE contract and the
client can be built against it now; the agent graph replaces the body in
Sprint 4 without changing the wire format.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from preflight import __version__
from preflight.decode.notam import NotamParseError, parse_notam
from preflight.schemas import FlightRequest, NotamRecord

app = FastAPI(
    title="Preflight",
    version=__version__,
    description="Agentic route-risk briefing. Research system — not for operational use.",
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


async def _brief_events(req: FlightRequest) -> AsyncIterator[dict[str, str]]:
    """Section-by-section stream. Each event is a JSON payload with a ``section`` key."""
    started = datetime.now(UTC)
    yield {"event": "start", "data": json.dumps({
        "departure": req.departure, "destination": req.destination,
        "generated_at": started.isoformat(),
    })}
    for section in ("notams", "weather", "precedent", "forecast"):
        await asyncio.sleep(0.05)
        yield {"event": "section", "data": json.dumps({
            "section": section, "status": "not_implemented",
            "note": "agent graph lands in Sprint 4",
        })}
    yield {"event": "done", "data": json.dumps({
        "findings": 0, "abstentions": 0,
        "latency_ms": int((datetime.now(UTC) - started).total_seconds() * 1000),
    })}


@app.post("/brief")
async def brief(req: FlightRequest) -> EventSourceResponse:
    return EventSourceResponse(_brief_events(req))
