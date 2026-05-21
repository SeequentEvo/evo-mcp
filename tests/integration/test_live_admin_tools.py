# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from evo_mcp.tools.admin_tools import register_admin_tools
from tests.helpers import FakeMCP
from tests.integration.live_test_support import ensure_deterministic_live_context, get_required_workspace


async def _get_admin_tools() -> FakeMCP:
    await ensure_deterministic_live_context()

    mcp = FakeMCP()
    register_admin_tools(mcp)
    return mcp


@pytest.mark.integration
async def test_live_get_workspace_summary_read_only():
    """Given an accessible workspace, when summary stats are requested, then schema counts are returned."""
    mcp = await _get_admin_tools()
    workspace = await get_required_workspace()

    tool = mcp.tools["get_workspace_summary"]
    result = await tool(workspace_id=str(workspace.id))

    assert result["workspace_id"] == str(workspace.id)
    assert result["total_objects"] >= 0
    assert isinstance(result["objects_by_schema"], dict)


@pytest.mark.integration
async def test_live_create_workspace_snapshot_read_only_without_blobs():
    """Given an accessible workspace, when a snapshot is created without blob expansion, then snapshot metadata is returned."""
    mcp = await _get_admin_tools()
    workspace = await get_required_workspace()

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
