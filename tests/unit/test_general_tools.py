# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

import evo_mcp.tools.general_tools as general_tools
from tests.helpers import FakeMCP, FakePage


pytestmark = pytest.mark.unit


def _register_general_tools() -> FakeMCP:
    mcp = FakeMCP()
    general_tools.register_general_tools(mcp)
    return mcp


@pytest.mark.asyncio
async def test_get_workspace_requires_identifier(monkeypatch):
    """Given no workspace identifier, when get_workspace is called, then it raises ValueError."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    mcp = _register_general_tools()

    tool = mcp.tools["get_workspace"]
    with pytest.raises(ValueError, match="Either workspace_id or workspace_name"):
        await tool()


@pytest.mark.asyncio
async def test_get_workspace_by_name_not_found(monkeypatch):
    """Given no matching workspace name, when looked up, then a not-found ValueError is raised."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    workspace_client = SimpleNamespace(
        list_workspaces=AsyncMock(return_value=FakePage(items=[]))
    )
    monkeypatch.setattr(general_tools.evo_context, "workspace_client", workspace_client)

    mcp = _register_general_tools()

    tool = mcp.tools["get_workspace"]
    with pytest.raises(ValueError, match="not found"):
        await tool(workspace_name="does-not-exist")


@pytest.mark.asyncio
async def test_list_workspaces_maps_shape(monkeypatch):
    """Given SDK workspace objects, when listed, then output is mapped to response dictionaries."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    ws = SimpleNamespace(
        id=uuid4(),
        display_name="Project A",
        description="desc",
        user_role=SimpleNamespace(name="ADMIN"),
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
    )
    workspace_client = SimpleNamespace(list_workspaces=AsyncMock(return_value=FakePage(items=[ws])))
    monkeypatch.setattr(general_tools.evo_context, "workspace_client", workspace_client)

    mcp = _register_general_tools()

    tool = mcp.tools["list_workspaces"]
    result = await tool(limit=1)

    assert len(result) == 1
    assert result[0]["name"] == "Project A"
    assert result[0]["user_role"] == "ADMIN"


@pytest.mark.asyncio
async def test_select_instance_switches_by_name(monkeypatch):
    """Given a matching instance name, when selected, then evo_context.switch_instance is called."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    target = SimpleNamespace(
        id=uuid4(),
        display_name="Sandbox",
        hubs=[SimpleNamespace(url="https://sandbox.example")],
    )
    discovery_client = SimpleNamespace(list_organizations=AsyncMock(return_value=[target]))
    switch_instance = AsyncMock()

    monkeypatch.setattr(general_tools.evo_context, "discovery_client", discovery_client)
    monkeypatch.setattr(general_tools.evo_context, "switch_instance", switch_instance)

    mcp = _register_general_tools()

    tool = mcp.tools["select_instance"]
    result = await tool(instance_name="Sandbox")

    switch_instance.assert_awaited_once_with(target.id, "https://sandbox.example")
    assert result.display_name == "Sandbox"


@pytest.mark.asyncio
async def test_workspace_health_check_includes_workspace_and_object_services(monkeypatch):
    """Given workspace and object clients, when health is checked, then both service statuses are returned."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    workspace_health = SimpleNamespace(service="workspace", status="ok")
    object_health = SimpleNamespace(service="objects", status="ok")
    workspace_client = SimpleNamespace(get_service_health=AsyncMock(return_value=workspace_health))
    object_client = SimpleNamespace(get_service_health=AsyncMock(return_value=object_health))
    get_object_client = AsyncMock(return_value=object_client)

    monkeypatch.setattr(general_tools.evo_context, "workspace_client", workspace_client)
    monkeypatch.setattr(general_tools.evo_context, "get_object_client", get_object_client)

    mcp = _register_general_tools()

    tool = mcp.tools["workspace_health_check"]
    workspace_id = str(uuid4())
    result = await tool(workspace_id=workspace_id)

    assert result == {
        "workspace_service": {"service": "workspace", "status": "ok"},
        "object_service": {"service": "objects", "status": "ok"},
    }
    get_object_client.assert_awaited_once_with(general_tools.UUID(workspace_id))


@pytest.mark.asyncio
async def test_list_objects_maps_shape(monkeypatch):
    """Given SDK object results, when listed, then object metadata is mapped to response dictionaries."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    health = SimpleNamespace(raise_for_status=lambda: None)
    obj = SimpleNamespace(
        id=uuid4(),
        name="Block Model",
        path="/models/block.json",
        schema_id=SimpleNamespace(sub_classification="pointset"),
        version_id="v1",
        created_at=datetime(2026, 1, 3, tzinfo=timezone.utc),
    )
    object_client = SimpleNamespace(
        get_service_health=AsyncMock(return_value=health),
        list_objects=AsyncMock(return_value=FakePage(items=[obj])),
    )
    get_object_client = AsyncMock(return_value=object_client)
    monkeypatch.setattr(general_tools.evo_context, "get_object_client", get_object_client)

    mcp = _register_general_tools()

    tool = mcp.tools["list_objects"]
    workspace_id = str(uuid4())
    result = await tool(workspace_id=workspace_id, deleted=True, limit=5)

    assert result == [
        {
            "id": str(obj.id),
            "name": "Block Model",
            "path": "/models/block.json",
            "schema_id": "pointset",
            "version_id": "v1",
            "created_at": "2026-01-03T00:00:00+00:00",
        }
    ]
    object_client.list_objects.assert_awaited_once_with(schema_id=None, deleted=True, limit=5)
    get_object_client.assert_awaited_once_with(general_tools.UUID(workspace_id))


@pytest.mark.asyncio
async def test_get_object_by_path_maps_metadata(monkeypatch):
    """Given an object path, when object metadata is fetched, then the downloaded metadata is mapped correctly."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    metadata = SimpleNamespace(
        id=uuid4(),
        name="Samples",
        path="/samples/points.json",
        schema_id=SimpleNamespace(sub_classification="pointset"),
        version_id="version-7",
        created_at=datetime(2026, 1, 4, tzinfo=timezone.utc),
    )
    object_client = SimpleNamespace(
        download_object_by_path=AsyncMock(return_value=SimpleNamespace(metadata=metadata))
    )
    get_object_client = AsyncMock(return_value=object_client)

    monkeypatch.setattr(general_tools.evo_context, "get_object_client", get_object_client)

    mcp = _register_general_tools()

    tool = mcp.tools["get_object"]
    workspace_id = str(uuid4())
    result = await tool(
        workspace_id=workspace_id,
        object_path="/samples/points.json",
        version="version-7",
    )

    assert result == {
        "id": str(metadata.id),
        "name": "Samples",
        "path": "/samples/points.json",
        "schema_id": "pointset",
        "version_id": "version-7",
        "created_at": "2026-01-04T00:00:00+00:00",
    }
    object_client.download_object_by_path.assert_awaited_once_with(
        "/samples/points.json",
        version="version-7",
    )
    get_object_client.assert_awaited_once_with(general_tools.UUID(workspace_id))


@pytest.mark.asyncio
async def test_get_object_requires_identifier(monkeypatch):
    """Given no object identifier, when get_object is called, then it raises ValueError."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())
    monkeypatch.setattr(general_tools.evo_context, "get_object_client", AsyncMock())

    mcp = _register_general_tools()

    tool = mcp.tools["get_object"]
    with pytest.raises(ValueError, match="Either object_id or object_path"):
        await tool(workspace_id=str(uuid4()))


@pytest.mark.asyncio
async def test_list_my_instances_reports_selected_instance(monkeypatch):
    """Given a selected instance, when listing instances, then context info is emitted and discovery results are returned."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    selected_org_id = uuid4()
    instances = [SimpleNamespace(id=selected_org_id, display_name="Sandbox")]
    discovery_client = SimpleNamespace(list_organizations=AsyncMock(return_value=instances))
    ctx = SimpleNamespace(info=AsyncMock())

    monkeypatch.setattr(general_tools.evo_context, "org_id", selected_org_id)
    monkeypatch.setattr(general_tools.evo_context, "discovery_client", discovery_client)

    mcp = _register_general_tools()

    tool = mcp.tools["list_my_instances"]
    result = await tool(ctx=ctx)

    assert result == instances
    ctx.info.assert_awaited_once_with(f"Selected instance ID {selected_org_id}")
