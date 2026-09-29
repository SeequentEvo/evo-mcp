# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Exercise the real server mode wiring in isolated interpreters."""

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("tool_filter", ["all", "data", "compute"])
def test_hosted_catalog_has_binary_input_and_no_local_filesystem_tools(tool_filter, tmp_path):
    source = Path(__file__).resolve().parents[1] / "src"
    script = """
import asyncio
from fastmcp import Client
import mcp_tools

async def check():
    async with Client(mcp_tools.mcp) as client:
        assert (await client.list_tools())
    tools = {tool.name: tool for tool in await mcp_tools.mcp.list_tools()}
    assert 'prepare_file_upload' in tools
    assert 'preview_csv_file' in tools
    assert 'configure_local_data_directory' not in tools
    assert 'list_local_data_files' not in tools
    assert 'original bytes' in mcp_tools.SERVER_INSTRUCTIONS
    if mcp_tools.TOOL_FILTER in ('all', 'data'):
        assert 'file_ref' in tools['upload_file'].parameters['properties']
        assert 'content_base64' not in tools['upload_file'].parameters['properties']
        assert 'file_ref' in mcp_tools.data_prompt()
    if mcp_tools.TOOL_FILTER in ('all', 'compute'):
        assert 'staging_create_object' in tools

asyncio.run(check())
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        env={
            **os.environ,
            "PYTHONPATH": str(source),
            "EVO_MCP_REMOTE_FILE_TRANSFER": "true",
            "MCP_TRANSPORT": "http",
            "CLIENT_DELEGATED_AUTH": "false",
            "MCP_TOOL_FILTER": tool_filter,
            "MCP_TOOL_STRATEGY": "none",
            "EVO_MCP_STATE_DIR": str(tmp_path),
            "EVO_MCP_CACHE_DIR": str(tmp_path / "cache"),
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
