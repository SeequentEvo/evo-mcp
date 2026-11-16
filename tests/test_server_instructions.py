# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Verify the server delivers instructions on both MCP protocol eras.

Backs the PR review question "do all clients implement the ability to read these
server instructions?". MCP carries ``instructions`` in ``initialize`` on legacy
connections and ``server/discover`` on modern ones. Whether a client injects
them into the model prompt is client-dependent — which is exactly why the same
critical preconditions are also encoded in tool descriptions and in the
always-visible bootstrap pins (covered by ``test_tool_strategy.py``).
"""

from __future__ import annotations

import asyncio

from fastmcp import Client, FastMCP


def _client_metadata(mcp: FastMCP, mode: str) -> tuple[str | None, str | None]:
    async def go() -> tuple[str | None, str | None]:
        async with Client(mcp, mode=mode) as client:
            return client.protocol_version, client.instructions

    return asyncio.run(go())


def test_instructions_are_delivered_on_modern_discovery():
    mcp = FastMCP("test-server", instructions="SELECT AN INSTANCE FIRST")
    assert _client_metadata(mcp, "auto") == ("2026-07-28", "SELECT AN INSTANCE FIRST")


def test_instructions_are_delivered_on_legacy_initialize():
    mcp = FastMCP("test-server", instructions="SELECT AN INSTANCE FIRST")
    assert _client_metadata(mcp, "legacy") == ("2025-11-25", "SELECT AN INSTANCE FIRST")


def test_real_server_delivers_precondition_instructions_on_both_eras():
    # Import here so the module-level server build (and its logging) only happens
    # when this test runs. mcp_tools lives at the src root (PYTHONPATH=src).
    import mcp_tools

    for mode in ("auto", "legacy"):
        _, instructions = _client_metadata(mcp_tools.mcp, mode)
        assert instructions, "server must ship non-empty instructions"
        assert "select_instance" in instructions
        assert "search_tools" in instructions
