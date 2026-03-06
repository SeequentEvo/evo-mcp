from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

import evo_mcp.tools.general_tools as general_tools
from tests.helpers import FakeMCP, FakePage


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_get_workspace_requires_identifier(monkeypatch):
    """Given no workspace identifier, when get_workspace is called, then it raises ValueError."""
    monkeypatch.setattr(general_tools, "ensure_initialized", AsyncMock())

    mcp = FakeMCP()
    general_tools.register_general_tools(mcp)

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

    mcp = FakeMCP()
    general_tools.register_general_tools(mcp)

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

    mcp = FakeMCP()
    general_tools.register_general_tools(mcp)

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

    mcp = FakeMCP()
    general_tools.register_general_tools(mcp)

    tool = mcp.tools["select_instance"]
    result = await tool(instance_name="Sandbox")

    switch_instance.assert_awaited_once_with(target.id, "https://sandbox.example")
    assert result.display_name == "Sandbox"
