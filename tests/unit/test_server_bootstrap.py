from __future__ import annotations

import importlib
import sys

import pytest


pytestmark = pytest.mark.unit


def _reload_mcp_tools(monkeypatch, tool_filter: str, transport: str):
    monkeypatch.setenv("MCP_TOOL_FILTER", tool_filter)
    monkeypatch.setenv("MCP_TRANSPORT", transport)

    if "mcp_tools" in sys.modules:
        del sys.modules["mcp_tools"]

    return importlib.import_module("mcp_tools")


def test_invalid_transport_defaults_to_stdio(monkeypatch):
    """Given an invalid MCP_TRANSPORT, when module config loads, then transport defaults to stdio."""
    module = _reload_mcp_tools(monkeypatch, tool_filter="all", transport="invalid")
    assert module.TRANSPORT == "stdio"


def test_invalid_tool_filter_defaults_to_all(monkeypatch):
    """Given an invalid MCP_TOOL_FILTER, when module config loads, then filter defaults to all."""
    module = _reload_mcp_tools(monkeypatch, tool_filter="invalid", transport="stdio")
    assert module.TOOL_FILTER == "all"
