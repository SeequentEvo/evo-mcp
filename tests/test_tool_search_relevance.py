# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Practical relevance check for the tool-search strategy.

Backs the PR review question "when used in practice does this approach feel good
for finding relevant tools?". Instead of answering by intuition, this registers
the *real* Evo tool catalog, hides it behind tool-search, and asserts that a
natural-language query surfaces the expected tool within the top-N results.

Run just this file with::

    PYTHONPATH=src uv run pytest tests/test_tool_search_relevance.py -q
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import FastMCP

from evo_mcp.tool_strategy import SearchEngine, ToolStrategy, apply_strategy
from evo_mcp.tools import (
    register_admin_tools,
    register_compute_tools,
    register_file_tools,
    register_filesystem_tools,
    register_general_tools,
    register_instance_users_admin_tools,
    register_object_builder_tools,
    register_object_staging_tools,
)

# Realistic natural-language queries a user/agent would issue, mapped to the tool
# we expect tool-search to surface. This is the evidence behind the review reply.
BM25_QUERY_EXPECTATIONS = [
    ("list my workspaces", "list_workspaces"),
    ("list my evo instances", "list_my_instances"),
    ("download a file", "download_file"),
    ("upload a file", "upload_file"),
    ("create a new workspace", "create_workspace"),
    ("run kriging interpolation", "kriging_run"),
    ("run inverse distance weighting estimation", "idw_run"),
    ("build IDW parameters", "idw_build_parameters"),
    ("list objects in a workspace", "list_objects"),
    ("add users to an instance", "add_users_to_instance"),
    ("find duplicate objects", "find_duplicate_objects"),
]

# The regex engine matches a literal pattern against tool names/descriptions, so
# it is exercised with precise fragments rather than free-form questions. Note a
# deliberately broad pattern (e.g. "workspace") matches many tools and can be
# truncated by max_results — regex rewards specificity, BM25 handles fuzzy intent.
REGEX_PATTERN_EXPECTATIONS = [
    ("kriging", "kriging_run"),
    ("idw_run", "idw_run"),
    ("download", "download_file"),
    ("create_workspace", "create_workspace"),
]


def _build_real_catalog(engine: SearchEngine) -> FastMCP:
    mcp = FastMCP("relevance-test")
    for register in (
        register_general_tools,
        register_admin_tools,
        register_instance_users_admin_tools,
        register_filesystem_tools,
        register_object_builder_tools,
        register_file_tools,
        register_compute_tools,
        register_object_staging_tools,
    ):
        register(mcp)
    apply_strategy(mcp, ToolStrategy.TOOL_SEARCH, search_engine=engine)
    return mcp


def _search(mcp: FastMCP, **query) -> list[str]:
    result = asyncio.run(mcp.call_tool("search_tools", query))
    if result.structured_content is None:
        return []
    return [tool["name"] for tool in result.structured_content["result"]]


@pytest.mark.parametrize("query, expected_tool", BM25_QUERY_EXPECTATIONS)
def test_bm25_query_surfaces_expected_tool(query, expected_tool):
    mcp = _build_real_catalog(SearchEngine.BM25)
    hits = _search(mcp, query=query)
    assert expected_tool in hits, f"'{query}' did not surface {expected_tool!r} in top results: {hits}"


@pytest.mark.parametrize("pattern, expected_tool", REGEX_PATTERN_EXPECTATIONS)
def test_regex_pattern_surfaces_expected_tool(pattern, expected_tool):
    mcp = _build_real_catalog(SearchEngine.REGEX)
    hits = _search(mcp, pattern=pattern)
    assert expected_tool in hits, f"pattern '{pattern}' did not surface {expected_tool!r}: {hits}"
