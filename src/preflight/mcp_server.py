"""Preflight as MCP tools.

``preflight mcp`` speaks the Model Context Protocol over stdio, so Claude
Desktop, Claude Code or any MCP client can call the briefing, the NOTAM
decoder and the precedent search as tools. Same code paths as the CLI and
API; the retrieval models load on first use so the server starts instantly.

Claude Desktop config (claude_desktop_config.json):

    {"mcpServers": {"preflight": {"command": "/path/to/preflight/.venv/bin/preflight",
                                  "args": ["mcp"]}}}
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from mcp.server.mcpserver import MCPServer

from preflight import __version__
from preflight.brief import build_briefing, render_text, with_precedent
from preflight.db import get_pool
from preflight.decode.notam import NotamParseError, parse_notam
from preflight.schemas import FlightRequest

server = MCPServer(
    "preflight",
    instructions=(
        "Route-risk briefing for flight operations. RESEARCH SYSTEM — not certified, not for "
        "operational use. Every claim in a briefing cites a source record; 'abstentions' list "
        "what could not be determined. Precedent comes from NASA ASRS and NTSB reports."
    ),
)

_retriever: Any = None
_retriever_loaded = False


def _get_retriever() -> Any:
    global _retriever, _retriever_loaded
    if not _retriever_loaded:
        from preflight.brief import load_retriever

        _retriever = load_retriever()
        _retriever_loaded = True
    return _retriever


@server.tool(
    name="brief",
    description=(
        "Build a route-risk briefing for a flight: NOTAMs in force, current weather and forecast "
        "coverage at each airport, and prior ASRS/NTSB reports for each hazard. Returns the "
        "briefing as text plus the structured JSON. off_block is ISO-8601 UTC, e.g. "
        "2026-09-12T14:00Z. Findings are ranked by severity; abstentions are explicit."
    ),
)
def brief(
    departure: str,
    destination: str,
    off_block: str,
    alternates: list[str] | None = None,
    aircraft_type: str | None = None,
    precedent: bool = True,
) -> dict[str, Any]:
    req = FlightRequest(
        departure=departure.upper(), destination=destination.upper(),
        alternates=tuple(a.upper() for a in (alternates or [])),
        off_block=datetime.fromisoformat(off_block.replace("Z", "+00:00")),
        aircraft_type=aircraft_type,
    )
    with get_pool().connection() as conn:
        b = build_briefing(conn, req)
        if precedent:
            b = with_precedent(conn, b, _get_retriever())
    return {"text": render_text(b), "briefing": b.model_dump(mode="json")}


@server.tool(
    name="decode_notam",
    description=(
        "Decode a raw NOTAM (ICAO format such as 'A1477/26 NOTAMN Q) ... E) RWY 28R CLSD' or US "
        "domestic '!SFO 09/142 SFO RWY 28R CLSD ...') into structured fields: validity window, "
        "Q-code meaning, entities (runway/taxiway/navaid with state and cause), hazard class and "
        "severity, plus the body with contractions expanded."
    ),
)
def decode_notam(text: str) -> dict[str, Any]:
    try:
        return parse_notam(text).model_dump(mode="json")
    except NotamParseError as e:
        return {"error": str(e)}


@server.tool(
    name="search_precedent",
    description=(
        "Search 75,000 NASA ASRS incident reports and NTSB investigations for prior reports "
        "matching a situation, e.g. 'lined up with a taxiway at night with the parallel runway "
        "closed'. Optional ICAO airport filter. Returns ranked passages with report ids."
    ),
)
def search_precedent(query: str, icao: str | None = None, k: int = 5) -> dict[str, Any]:
    r = _get_retriever()
    if r is None:
        return {"error": "retrieval models are not installed (uv sync --extra ml)", "hits": []}
    with get_pool().connection() as conn:
        hits = r.search(conn, query, k=k, icao=icao.upper() if icao else None, rerank=True)
    return {"hits": [
        {"source": h.source, "id": h.external_id, "title": h.title, "airport": h.icao,
         "score": h.rerank_score, "passage": h.text}
        for h in hits
    ]}


@server.tool(
    name="status",
    description="What the system currently holds: corpus size, last ingest runs, version.",
)
def status() -> dict[str, Any]:
    from preflight.db.corpus import stats
    from preflight.db.runs import last_runs

    with get_pool().connection() as conn:
        corpus = stats(conn)
        runs = [{"kind": r.kind, "source": r.source, "finished_at": r.finished_at.isoformat(),
                 "status": r.status, "counts": r.counts} for r in last_runs(conn)]
    return {"version": __version__, "now": datetime.now(UTC).isoformat(timespec="seconds"),
            "corpus": corpus, "last_ingest_runs": runs}


def main() -> None:
    server.run(transport="stdio")
