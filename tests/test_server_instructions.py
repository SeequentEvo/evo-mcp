# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Verify the server delivers its instructions over MCP discovery.

The modern MCP spec carries ``instructions`` in the ``server/discover`` result,
so any spec-compliant client *receives* them. Whether a client injects
them into the model prompt is client-dependent — which is exactly why the same
critical preconditions are also encoded in tool descriptions and in the
always-visible bootstrap pins (covered by ``test_tool_strategy.py``).
"""

from __future__ import annotations

import asyncio

import pytest
from fastmcp import Client, FastMCP
from mcp.shared.exceptions import MCPError


def _discover_instructions(mcp: FastMCP) -> str | None:
    async def go() -> str | None:
        async with Client(mcp, mode="auto") as client:
            return client.instructions

    return asyncio.run(go())


def test_instructions_are_delivered_on_discover():
    mcp = FastMCP("test-server", instructions="SELECT AN INSTANCE FIRST")
    assert _discover_instructions(mcp) == "SELECT AN INSTANCE FIRST"


def test_real_server_delivers_precondition_instructions():
    # Import here so the module-level server build (and its logging) only happens
    # when this test runs. mcp_tools lives at the src root (PYTHONPATH=src).
    import mcp_tools

    instructions = _discover_instructions(mcp_tools.mcp)
    assert instructions, "server must ship non-empty instructions"
    # The instance->workspace precondition and the tool-search hint are the two
    # behaviors the reviewer worried a client might miss; assert they are present
    # so a spec-compliant client always receives them.
    assert "select_instance" in instructions
    assert "search_tools" in instructions


def test_real_server_rejects_legacy_protocol():
    import mcp_tools

    async def connect() -> None:
        async with Client(mcp_tools.mcp, mode="legacy"):
            pass

    with pytest.raises(MCPError, match="requires the stateless MCP protocol"):
        asyncio.run(connect())
