"""HTTP surface.

``/decode`` and ``/brief`` are real. ``/brief/stream`` emits the same briefing
finding by finding over SSE so a client can render progressively; ``GET /``
serves the single-page briefing UI that consumes it. The agent layer (Sprint 4)
slots in behind the same events without changing the wire.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from preflight import __version__
from preflight.brief import build_briefing, load_retriever, with_precedent
from preflight.db import close_pool, get_pool
from preflight.decode.notam import NotamParseError, parse_notam
from preflight.schemas import Briefing, FlightRequest, NotamRecord
from preflight.verify.ground import load_verifier, with_verification

_retriever: Any = None
_verifier: Any = None


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _retriever, _verifier
    _retriever = load_retriever()
    _verifier = load_verifier()
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


_STATIC = Path(__file__).parent / "static"


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/decode", response_model=NotamRecord)
async def decode(req: DecodeRequest) -> NotamRecord:
    try:
        return parse_notam(req.text)
    except NotamParseError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e


def _build(req: FlightRequest, precedent: bool = True, verify: bool = True) -> Briefing:
    with get_pool().connection() as conn:
        b = build_briefing(conn, req)
        if precedent:
            b = with_precedent(conn, b, _retriever)
    return with_verification(b, _verifier) if verify else b


@app.post("/brief", response_model=Briefing)
async def brief(req: FlightRequest, precedent: bool = True, verify: bool = True) -> Briefing:
    return await asyncio.to_thread(_build, req, precedent, verify)


async def _brief_events(
    req: FlightRequest, precedent: bool = True
) -> AsyncIterator[dict[str, str]]:
    yield {"event": "start", "data": json.dumps({
        "departure": req.departure, "destination": req.destination,
        "alternates": list(req.alternates),
    })}
    b = await asyncio.to_thread(_build, req, precedent)
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
async def brief_stream(req: FlightRequest, precedent: bool = True) -> EventSourceResponse:
    return EventSourceResponse(_brief_events(req, precedent))


@app.get("/brief/stream")
async def brief_stream_get(
    departure: Annotated[str, Query(pattern=r"^[A-Za-z]{4}$")],
    destination: Annotated[str, Query(pattern=r"^[A-Za-z]{4}$")],
    off_block: datetime,
    alternates: Annotated[str, Query(description="comma-separated ICAO codes")] = "",
    aircraft_type: str | None = None,
    precedent: bool = True,
) -> EventSourceResponse:
    """Query-string form of the stream, for EventSource (which can only GET)."""
    req = FlightRequest(
        departure=departure.upper(), destination=destination.upper(),
        alternates=tuple(a.strip().upper() for a in alternates.split(",") if a.strip()),
        off_block=off_block, aircraft_type=aircraft_type or None,
    )
    return EventSourceResponse(_brief_events(req, precedent))
