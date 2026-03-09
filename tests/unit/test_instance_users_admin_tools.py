# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

import evo_mcp.tools.instance_users_admin_tools as instance_users_admin_tools
from tests.helpers import FakeMCP


pytestmark = pytest.mark.unit


class FakeApiPage:
    """Small raw-API page stub with items() and len() support."""

    def __init__(self, items: list):
        self._items = items

    def items(self):
        return self._items

    def __len__(self) -> int:
        return len(self._items)


def _register_instance_admin_tools() -> FakeMCP:
    mcp = FakeMCP()
    instance_users_admin_tools.register_instance_users_admin_tools(mcp)
    return mcp


def _fake_user(index: int) -> SimpleNamespace:
    return SimpleNamespace(
        user_id=str(uuid4()),
        email=f"user{index}@example.com",
        full_name=f"User {index}",
        roles=[SimpleNamespace(name="Evo User")],
    )


@pytest.mark.asyncio
async def test_get_users_in_instance_pages_and_respects_count(monkeypatch):
    """Given paged API results, when listing users with a count, then the result is trimmed to that count."""
    monkeypatch.setattr(instance_users_admin_tools, "ensure_initialized", AsyncMock())

    first_page = [_fake_user(index) for index in range(100)]
    second_page = [_fake_user(index) for index in range(100, 150)]
    workspace_client = SimpleNamespace(
        list_instance_users=AsyncMock(side_effect=[FakeApiPage(first_page), FakeApiPage(second_page)])
    )
    monkeypatch.setattr(instance_users_admin_tools.evo_context, "workspace_client", workspace_client)

    mcp = _register_instance_admin_tools()
    tool = mcp.tools["get_users_in_instance"]

    result = await tool(count=101)

    assert len(result) == 101
    assert result[0]["email"] == "user0@example.com"
    assert result[-1]["email"] == "user100@example.com"
    assert workspace_client.list_instance_users.await_args_list[0].kwargs == {"offset": 0, "limit": 100}
    assert workspace_client.list_instance_users.await_args_list[1].kwargs == {"offset": 100, "limit": 100}


@pytest.mark.asyncio
async def test_list_roles_in_instance_returns_workspace_roles(monkeypatch):
    """Given instance roles from the workspace client, when listed, then the response is returned unchanged."""
    monkeypatch.setattr(instance_users_admin_tools, "ensure_initialized", AsyncMock())

    roles = [SimpleNamespace(id=uuid4(), name="Evo User"), SimpleNamespace(id=uuid4(), name="Admin")]
    workspace_client = SimpleNamespace(list_instance_roles=AsyncMock(return_value=roles))
    monkeypatch.setattr(instance_users_admin_tools.evo_context, "workspace_client", workspace_client)

    mcp = _register_instance_admin_tools()
    tool = mcp.tools["list_roles_in_instance"]

    result = await tool()

    assert result == roles
    workspace_client.list_instance_roles.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_add_users_to_instance_maps_invitations_and_members(monkeypatch):
    """Given add-user results, when users are added, then invitations and members are mapped by email."""
    monkeypatch.setattr(instance_users_admin_tools, "ensure_initialized", AsyncMock())

    response = SimpleNamespace(
        invitations=[SimpleNamespace(email="external@example.com")],
        members=[SimpleNamespace(email="member@example.com")],
    )
    workspace_client = SimpleNamespace(add_users_to_instance=AsyncMock(return_value=response))
    monkeypatch.setattr(instance_users_admin_tools.evo_context, "workspace_client", workspace_client)

    mcp = _register_instance_admin_tools()
    tool = mcp.tools["add_users_to_instance"]
    role_ids = [uuid4()]

    result = await tool(
        user_emails=["external@example.com", "member@example.com"],
        role_ids=role_ids,
    )

    assert result == {
        "invitations_sent": ["external@example.com"],
        "members_added": ["member@example.com"],
    }
    workspace_client.add_users_to_instance.assert_awaited_once_with(
        users={
            "external@example.com": role_ids,
            "member@example.com": role_ids,
        }
    )


@pytest.mark.asyncio
async def test_remove_user_from_instance_calls_workspace_client(monkeypatch):
    """Given a user removal request, when the tool runs, then the workspace client is called and the removed email is returned."""
    monkeypatch.setattr(instance_users_admin_tools, "ensure_initialized", AsyncMock())

    workspace_client = SimpleNamespace(remove_instance_user=AsyncMock())
    monkeypatch.setattr(instance_users_admin_tools.evo_context, "workspace_client", workspace_client)

    mcp = _register_instance_admin_tools()
    tool = mcp.tools["remove_user_from_instance"]
    user_id = uuid4()

    result = await tool(user_email="user@example.com", user_id=user_id)

    assert result == {"user_removed": "user@example.com"}
    workspace_client.remove_instance_user.assert_awaited_once_with(user_id=user_id)


@pytest.mark.asyncio
async def test_update_user_role_in_instance_calls_workspace_client(monkeypatch):
    """Given a role update request, when the tool runs, then the workspace client is called and the new roles are returned."""
    monkeypatch.setattr(instance_users_admin_tools, "ensure_initialized", AsyncMock())

    workspace_client = SimpleNamespace(update_instance_user_roles=AsyncMock())
    monkeypatch.setattr(instance_users_admin_tools.evo_context, "workspace_client", workspace_client)

    mcp = _register_instance_admin_tools()
    tool = mcp.tools["update_user_role_in_instance"]
    user_id = uuid4()
    role_ids = [uuid4(), uuid4()]

    result = await tool(user_email="user@example.com", user_id=user_id, role_ids=role_ids)

    assert result == {
        "user_role_updated": "user@example.com",
        "new_roles": role_ids,
    }
    workspace_client.update_instance_user_roles.assert_awaited_once_with(user_id=user_id, roles=role_ids)


@pytest.mark.asyncio
async def test_instance_user_tools_require_connected_workspace_client(monkeypatch):
    """Given no selected instance, when an instance-user admin tool runs, then a clear ValueError is raised."""
    monkeypatch.setattr(instance_users_admin_tools, "ensure_initialized", AsyncMock())
    monkeypatch.setattr(instance_users_admin_tools.evo_context, "workspace_client", None)

    mcp = _register_instance_admin_tools()
    tool = mcp.tools["list_roles_in_instance"]

    with pytest.raises(ValueError, match="Please ensure you are connected to an instance"):
        await tool()
