# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit


SRC_PATH = Path(__file__).resolve().parents[2] / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def _reload_mcp_tools(monkeypatch, tool_filter: str, transport: str):
    monkeypatch.setenv("MCP_TOOL_FILTER", tool_filter)
    monkeypatch.setenv("MCP_TRANSPORT", transport)

    if "mcp_tools" in sys.modules:
        del sys.modules["mcp_tools"]

    return importlib.import_module("mcp_tools")


def _registered_component_names(module, prefix: str) -> set[str]:
    components = module.mcp._local_provider._components
    return {
        key.removeprefix(f"{prefix}:").split("@", 1)[0]
        for key in components
        if key.startswith(f"{prefix}:")
    }


def test_invalid_transport_defaults_to_stdio(monkeypatch):
    """Given an invalid MCP_TRANSPORT, when module config loads, then transport defaults to stdio."""
    module = _reload_mcp_tools(monkeypatch, tool_filter="all", transport="invalid")
    assert module.TRANSPORT == "stdio"


def test_invalid_tool_filter_defaults_to_all(monkeypatch):
    """Given an invalid MCP_TOOL_FILTER, when module config loads, then filter defaults to all."""
    module = _reload_mcp_tools(monkeypatch, tool_filter="invalid", transport="stdio")
    assert module.TOOL_FILTER == "all"


def test_all_mode_registers_general_admin_and_data_tools(monkeypatch):
    """Given all mode, when the server boots, then all tool groups and prompts are registered."""
    module = _reload_mcp_tools(monkeypatch, tool_filter="all", transport="stdio")

    tool_names = _registered_component_names(module, "tool")
    prompt_names = _registered_component_names(module, "prompt")
    resource_names = _registered_component_names(module, "resource")

    assert {
        "list_workspaces",
        "create_workspace",
        "get_users_in_instance",
        "configure_local_data_directory",
        "build_and_create_pointset",
    }.issubset(tool_names)
    assert {"all_prompt", "admin_prompt", "data_prompt"}.issubset(prompt_names)
    assert "evo://objects/schema-reference" in resource_names


def test_admin_mode_excludes_data_tools_and_data_prompts(monkeypatch):
    """Given admin mode, when the server boots, then admin tools remain and data-only registrations are absent."""
    module = _reload_mcp_tools(monkeypatch, tool_filter="admin", transport="stdio")

    tool_names = _registered_component_names(module, "tool")
    prompt_names = _registered_component_names(module, "prompt")

    assert {"list_workspaces", "create_workspace", "get_users_in_instance"}.issubset(tool_names)
    assert "configure_local_data_directory" not in tool_names
    assert "build_and_create_pointset" not in tool_names
    assert "admin_prompt" in prompt_names
    assert "data_prompt" not in prompt_names
    assert "all_prompt" not in prompt_names


def test_data_mode_excludes_admin_tools_and_registers_data_prompt(monkeypatch):
    """Given data mode, when the server boots, then data tools remain and admin-only registrations are absent."""
    module = _reload_mcp_tools(monkeypatch, tool_filter="data", transport="stdio")

    tool_names = _registered_component_names(module, "tool")
    prompt_names = _registered_component_names(module, "prompt")

    assert {"list_workspaces", "configure_local_data_directory", "build_and_create_pointset"}.issubset(tool_names)
    assert "create_workspace" not in tool_names
    assert "get_users_in_instance" not in tool_names
    assert "data_prompt" in prompt_names
    assert "admin_prompt" not in prompt_names
    assert "all_prompt" not in prompt_names
