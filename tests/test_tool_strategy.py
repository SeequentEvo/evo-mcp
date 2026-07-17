# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the tool-exposure strategy (``evo_mcp.tool_strategy``)."""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP

from evo_mcp.tool_strategy import (
    SearchEngine,
    ToolStrategy,
    apply_strategy,
)
from evo_mcp.tools import register_general_tools

# The bootstrap tools pinned by mcp_tools.py so agents can always find their
# entry point regardless of strategy. Kept in sync with mcp_tools.apply_strategy.
BOOTSTRAP_TOOLS = ["select_instance", "list_my_instances"]


def _build_server() -> FastMCP:
    # Uses a real FastMCP server (not a lightweight tool-capturing fake) because
    # this suite verifies the tool-search *transform* layer: apply_strategy calls
    # mcp.add_transform(...), and the collapsed catalog is only observable through
    # mcp.list_tools(run_middleware=True). A decorator-capturing stub cannot
    # exercise transforms or list_tools, so it would test nothing meaningful here.
    mcp = FastMCP("test-server")

    @mcp.tool()
    def alpha() -> str:
        return "a"

    @mcp.tool()
    def beta() -> str:
        return "b"

    @mcp.tool()
    def select_instance() -> str:
        return "s"

    return mcp


def _visible_tool_names(mcp: FastMCP) -> list[str]:
    tools = asyncio.run(mcp.list_tools(run_middleware=True))
    return sorted(t.name for t in tools)


def _search(mcp: FastMCP, **query) -> list[str]:
    """Invoke the synthetic ``search_tools`` tool and return matched tool names.

    The BM25 engine expects a ``query`` kwarg; the regex engine expects a
    ``pattern`` kwarg — pass whichever the engine under test uses.
    """
    result = asyncio.run(mcp.call_tool("search_tools", query))
    if result.structured_content is None:
        return []
    return [tool["name"] for tool in result.structured_content["result"]]


# --- apply_strategy behavior ----------------------------------------------


def test_tool_search_uses_bm25_by_default():
    mcp = _build_server()
    applied = apply_strategy(mcp, ToolStrategy.TOOL_SEARCH)
    assert applied is ToolStrategy.TOOL_SEARCH
    assert "search_tools" in _visible_tool_names(mcp)


# --- apply_strategy behavior ----------------------------------------------


def test_none_strategy_lists_full_catalog():
    mcp = _build_server()
    applied = apply_strategy(mcp, ToolStrategy.NONE)
    assert applied is ToolStrategy.NONE
    assert _visible_tool_names(mcp) == ["alpha", "beta", "select_instance"]


def test_tool_search_collapses_catalog():
    mcp = _build_server()
    applied = apply_strategy(mcp, ToolStrategy.TOOL_SEARCH)
    assert applied is ToolStrategy.TOOL_SEARCH
    names = _visible_tool_names(mcp)
    assert "search_tools" in names
    assert "call_tool" in names
    # Regular catalog tools are hidden behind search.
    assert "alpha" not in names
    assert "beta" not in names


def test_tool_search_pins_always_visible():
    mcp = _build_server()
    apply_strategy(mcp, ToolStrategy.TOOL_SEARCH, always_visible=["select_instance"])
    names = _visible_tool_names(mcp)
    assert "select_instance" in names
    assert "search_tools" in names
    assert "alpha" not in names


@pytest.mark.parametrize("engine", [SearchEngine.BM25, SearchEngine.REGEX])
def test_tool_search_supports_both_engines(engine):
    mcp = _build_server()
    apply_strategy(mcp, ToolStrategy.TOOL_SEARCH, search_engine=engine)
    names = _visible_tool_names(mcp)
    assert "search_tools" in names


def test_bm25_search_resolves_hidden_tool_by_name():
    mcp = _build_server()
    apply_strategy(mcp, ToolStrategy.TOOL_SEARCH, search_engine=SearchEngine.BM25)
    # A tool hidden behind search is still reachable via a natural-language query,
    # confirming the search index was built from the registered catalog.
    assert "alpha" in _search(mcp, query="alpha")


def test_regex_search_resolves_hidden_tool_by_pattern():
    mcp = _build_server()
    apply_strategy(mcp, ToolStrategy.TOOL_SEARCH, search_engine=SearchEngine.REGEX)
    # The regex engine exposes a ``pattern`` argument (not ``query``).
    assert "beta" in _search(mcp, pattern="beta")


def test_unhandled_strategy_raises():
    mcp = _build_server()
    with pytest.raises(ValueError, match="Unhandled tool strategy"):
        apply_strategy(mcp, "unexpected")  # type: ignore[arg-type]


# --- integration with the real tool catalog --------------------------------


def test_real_bootstrap_tools_stay_pinned_under_tool_search():
    # Guardrail against the mock tests' blind spot: if a real bootstrap tool is
    # renamed, the always_visible list in mcp_tools.py would silently stop pinning
    # it. Register the real general tools and assert the pinned names still exist
    # and remain directly visible when the catalog is hidden behind search.
    mcp = FastMCP("test-server")
    register_general_tools(mcp)
    apply_strategy(mcp, ToolStrategy.TOOL_SEARCH, always_visible=BOOTSTRAP_TOOLS)
    names = _visible_tool_names(mcp)
    for tool_name in BOOTSTRAP_TOOLS:
        assert tool_name in names
    assert "search_tools" in names
