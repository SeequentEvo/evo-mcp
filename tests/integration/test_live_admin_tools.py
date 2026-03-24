# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os

import pytest

from evo_mcp.context import ensure_initialized, evo_context
from evo_mcp.tools.admin_tools import register_admin_tools
from tests.helpers import FakeMCP


_REQUIRED_ENV_VARS = [
    "EVO_CLIENT_ID",
    "EVO_REDIRECT_URL",
    "EVO_DISCOVERY_URL",
]


def _require_live_env() -> None:
    if os.getenv("RUN_EVO_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_EVO_LIVE_TESTS=1 to run live Evo integration tests")

    missing = [name for name in _REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing required environment variables: {', '.join(missing)}")


async def _get_admin_tools() -> FakeMCP:
    _require_live_env()
    await ensure_initialized()

    mcp = FakeMCP()
    register_admin_tools(mcp)
    return mcp


async def _get_first_workspace():
    page = await evo_context.workspace_client.list_workspaces(limit=5)
    workspaces = page.items()
    if not workspaces:
        pytest.skip("No accessible workspaces were returned for this account")
    return workspaces[0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_get_workspace_summary_read_only():
    """Given an accessible workspace, when summary stats are requested, then schema counts are returned."""
    mcp = await _get_admin_tools()
    workspace = await _get_first_workspace()

    tool = mcp.tools["get_workspace_summary"]
    result = await tool(workspace_id=str(workspace.id))

    assert result["workspace_id"] == str(workspace.id)
    assert result["total_objects"] >= 0
    assert isinstance(result["objects_by_schema"], dict)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_create_workspace_snapshot_read_only_without_blobs():
    """Given an accessible workspace, when a snapshot is created without blob expansion, then snapshot metadata is returned."""
    mcp = await _get_admin_tools()
    workspace = await _get_first_workspace()

    tool = mcp.tools["create_workspace_snapshot"]
    result = await tool(
        workspace_id=str(workspace.id),
        snapshot_name="integration-snapshot",
        include_data_blobs=False,
    )

    assert result["summary"]["snapshot_name"] == "integration-snapshot"
    assert result["summary"]["workspace_id"] == str(workspace.id)
    assert result["snapshot"]["workspace_name"] == workspace.display_name
    assert isinstance(result["snapshot"]["objects"], list)
