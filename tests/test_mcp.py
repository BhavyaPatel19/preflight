"""MCP tools, called through the server without a transport."""

import json

import pytest

from preflight import mcp_server as M


def _payload(result):
    """The structured content of a CallToolResult, whichever field the SDK filled."""
    sc = getattr(result, "structuredContent", None) or getattr(result, "structured_content", None)
    if sc:
        return sc
    for block in result.content:
        if getattr(block, "type", "") == "text":
            return json.loads(block.text)
    raise AssertionError("no payload")


async def test_tools_are_listed_with_descriptions():
    tools = {t.name: t for t in await M.server.list_tools()}
    assert set(tools) >= {"brief", "decode_notam", "search_precedent", "status"}
    for t in tools.values():
        assert t.description and len(t.description) > 40
    assert "off_block" in json.dumps(tools["brief"].input_schema)
    assert "NOT certified" in (M.server.instructions or "") or "not certified" in (
        M.server.instructions or "").lower()


async def test_decode_notam_tool():
    res = await M.server.call_tool("decode_notam", {
        "text": "!SFO 09/142 SFO RWY 28R CLSD 2609102330-2609110700"})
    out = _payload(res)
    assert out["hazard_class"] == "runway_closure" and out["severity"] == "HIGH"


async def test_decode_notam_tool_reports_parse_errors_as_data():
    out = _payload(await M.server.call_tool("decode_notam", {"text": "nope"}))
    assert "error" in out


async def test_search_precedent_without_models_is_an_error_payload(monkeypatch):
    monkeypatch.setattr(M, "_retriever", None)
    monkeypatch.setattr(M, "_retriever_loaded", True)
    out = _payload(await M.server.call_tool("search_precedent", {"query": "x"}))
    assert out["hits"] == [] and "not installed" in out["error"]


@pytest.mark.db
async def test_brief_tool_end_to_end(db, monkeypatch):    # db: skip without Postgres
    monkeypatch.setattr(M, "_retriever", None)
    monkeypatch.setattr(M, "_retriever_loaded", True)
    out = _payload(await M.server.call_tool("brief", {
        "departure": "ksfo", "destination": "kjfk", "alternates": ["kbos"],
        "off_block": "2026-09-12T14:00Z", "precedent": True,
    }))
    assert out["text"].startswith("KSFO → KJFK (alt KBOS)")
    b = out["briefing"]
    assert b["request"]["departure"] == "KSFO"
    assert any(a["topic"] == "precedent" for a in b["abstentions"])   # models absent → says so


@pytest.mark.db
async def test_status_tool(db):
    out = _payload(await M.server.call_tool("status", {}))
    assert "corpus" in out and "version" in out
