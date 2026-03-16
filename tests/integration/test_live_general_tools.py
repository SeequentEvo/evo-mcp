# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evo_mcp.context import ensure_initialized, evo_context
from evo_mcp.tools.general_tools import register_general_tools
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


async def _get_general_tools() -> FakeMCP:
    _require_live_env()
    await ensure_initialized()

    mcp = FakeMCP()
    register_general_tools(mcp)
    return mcp


async def _get_first_workspace():
    page = await evo_context.workspace_client.list_workspaces(limit=5)
    workspaces = page.items()
    if not workspaces:
        pytest.skip("No accessible workspaces were returned for this account")
    return workspaces[0]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_workspace_health_check_read_only():
    """Given live Evo connectivity, when workspace health is checked, then a workspace service status is returned."""
    mcp = await _get_general_tools()

    tool = mcp.tools["workspace_health_check"]
    result = await tool()

    assert "workspace_service" in result
    assert result["workspace_service"]["service"]
    assert result["workspace_service"]["status"]


@pytest.mark.integration
@pytest.mark.asyncio
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
@pytest.mark.asyncio
async def test_live_get_workspace_by_id_read_only():
    """Given an accessible workspace, when fetched by ID, then the mapped workspace metadata is returned."""
    mcp = await _get_general_tools()
    workspace = await _get_first_workspace()

    tool = mcp.tools["get_workspace"]
    result = await tool(workspace_id=str(workspace.id))

    assert result["id"] == str(workspace.id)
    assert result["name"] == workspace.display_name
    assert "default_coordinate_system" in result
    assert "labels" in result


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_list_objects_read_only_for_first_workspace():
    """Given an accessible workspace, when objects are listed, then a read-only object listing response is returned."""
    mcp = await _get_general_tools()
    workspace = await _get_first_workspace()

    tool = mcp.tools["list_objects"]
    result = await tool(workspace_id=str(workspace.id), limit=5)

    assert isinstance(result, list)
    for obj in result:
        assert obj["id"]
        assert obj["name"]
        assert obj["path"]
        assert "schema_id" in obj


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_get_object_by_path_when_workspace_has_objects():
    """Given a workspace with at least one object, when fetched by path, then object metadata is returned."""
    mcp = await _get_general_tools()
    workspace = await _get_first_workspace()

    list_objects = mcp.tools["list_objects"]
    objects = await list_objects(workspace_id=str(workspace.id), limit=5)
    if not objects:
        pytest.skip("No objects were returned for the selected workspace")

    get_object = mcp.tools["get_object"]
    result = await get_object(
        workspace_id=str(workspace.id),
        object_path=objects[0]["path"],
    )

    assert result["id"]
    assert result["name"]
    assert result["path"] == objects[0]["path"]
    assert "schema_id" in result
