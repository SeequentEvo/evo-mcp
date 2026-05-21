# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evo_mcp.tools.general_tools import register_general_tools
from tests.helpers import FakeMCP
from tests.integration.live_test_support import (
    ensure_deterministic_live_context,
    get_required_object_path,
    get_required_workspace,
)


async def _get_general_tools() -> FakeMCP:
    await ensure_deterministic_live_context()

    mcp = FakeMCP()
    register_general_tools(mcp)
    return mcp


@pytest.mark.integration
async def test_live_workspace_health_check_read_only():
    """Given live Evo connectivity, when workspace health is checked, then a workspace service status is returned."""
    mcp = await _get_general_tools()

    tool = mcp.tools["workspace_health_check"]
    result = await tool()

    assert "workspace_service" in result
    assert result["workspace_service"]["service"]
    assert result["workspace_service"]["status"]


@pytest.mark.integration
async def test_live_list_my_instances_read_only():
    """Given live Evo connectivity, when instances are listed, then discovery results and selected-instance context are returned."""
    mcp = await _get_general_tools()

    ctx = SimpleNamespace(info=AsyncMock())
    tool = mcp.tools["list_my_instances"]
    instances = await tool(ctx=ctx)

    assert isinstance(instances, list)
    assert instances
    assert all(instance.id is not None for instance in instances)
    assert all(instance.display_name for instance in instances)
    ctx.info.assert_awaited()


@pytest.mark.integration
async def test_live_get_workspace_by_id_read_only():
    """Given an accessible workspace, when fetched by ID, then the mapped workspace metadata is returned."""
    mcp = await _get_general_tools()
    workspace = await get_required_workspace()

    tool = mcp.tools["get_workspace"]
    result = await tool(workspace_id=str(workspace.id))

    assert result["id"] == str(workspace.id)
    assert result["name"] == workspace.display_name
    assert "default_coordinate_system" in result
    assert "labels" in result


@pytest.mark.integration
async def test_live_list_objects_read_only_for_first_workspace():
    """Given an accessible workspace, when objects are listed, then a read-only object listing response is returned."""
    mcp = await _get_general_tools()
    workspace = await get_required_workspace()

    tool = mcp.tools["list_objects"]
    result = await tool(workspace_id=str(workspace.id), limit=5)

    assert isinstance(result, list)
    for obj in result:
        assert obj["id"]
        assert obj["name"]
        assert obj["path"]
        assert "schema_id" in obj


@pytest.mark.integration
async def test_live_get_object_by_path_when_workspace_has_objects():
    """Given a configured workspace and object path, when fetched by path, then object metadata is returned."""
    mcp = await _get_general_tools()
    workspace = await get_required_workspace()
    object_path = get_required_object_path()

    get_object = mcp.tools["get_object"]
    result = await get_object(
        workspace_id=str(workspace.id),
        object_path=object_path,
    )

    assert result["id"]
    assert result["name"]
    assert result["path"] == object_path
    assert "schema_id" in result
