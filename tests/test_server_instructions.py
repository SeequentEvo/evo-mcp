# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Verify the server delivers its instructions over the MCP initialize handshake.

Backs the PR review question "do all clients implement the ability to read these
server instructions?". The MCP spec carries ``instructions`` in the ``initialize``
result, so any spec-compliant client *receives* them. Whether a client injects
them into the model prompt is client-dependent — which is exactly why the same
critical preconditions are also encoded in tool descriptions and in the
always-visible bootstrap pins (covered by ``test_tool_strategy.py``).
"""

from __future__ import annotations

import asyncio

from fastmcp import Client, FastMCP


def _initialize_instructions(mcp: FastMCP) -> str | None:
    async def go() -> str | None:
        async with Client(mcp, mode="legacy") as client:
            return client.initialize_result.instructions

    return asyncio.run(go())


def test_instructions_are_delivered_on_initialize():
    mcp = FastMCP("test-server", instructions="SELECT AN INSTANCE FIRST")
    assert _initialize_instructions(mcp) == "SELECT AN INSTANCE FIRST"


def test_real_server_delivers_precondition_instructions():
    # Import here so the module-level server build (and its logging) only happens
    # when this test runs. mcp_tools lives at the src root (PYTHONPATH=src).
    import mcp_tools

    instructions = _initialize_instructions(mcp_tools.mcp)
    assert instructions, "server must ship non-empty instructions"
    # The instance->workspace precondition and the tool-search hint are the two
    # behaviors the reviewer worried a client might miss; assert they are present
    # so a spec-compliant client always receives them.
    assert "select_instance" in instructions
    assert "search_tools" in instructions
