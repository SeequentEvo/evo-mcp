# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest


pytestmark = pytest.mark.unit


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "setup_mcp.py"


def _load_setup_mcp_module():
    spec = importlib.util.spec_from_file_location("setup_mcp", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_load_env_file_parses_exported_and_quoted_values(tmp_path):
    """Given a .env file, when loaded, then exported and quoted values are normalized."""
    setup_mcp = _load_setup_mcp_module()

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# comment\n"
        "export EVO_CLIENT_ID=client-id\n"
        "EVO_REDIRECT_URL=\"http://localhost/callback\"\n"
        "MCP_TOOL_FILTER='data'\n",
        encoding="utf-8",
    )

    assert setup_mcp.load_env_file(tmp_path) == {
        "EVO_CLIENT_ID": "client-id",
        "EVO_REDIRECT_URL": "http://localhost/callback",
        "MCP_TOOL_FILTER": "data",
    }


def test_write_env_file_updates_existing_keys_and_appends_new_ones(tmp_path):
    """Given an existing .env file, when writing values, then keys are updated in place and new keys are appended."""
    setup_mcp = _load_setup_mcp_module()

    env_file = tmp_path / ".env"
    env_file.write_text(
        "# existing settings\n"
        "EVO_CLIENT_ID=old-client\n"
        "MCP_TOOL_FILTER=all\n",
        encoding="utf-8",
    )

    setup_mcp.write_env_file(
        tmp_path,
        {
            "EVO_CLIENT_ID": "new-client",
            "MCP_HTTP_PORT": "5000",
        },
    )

    assert env_file.read_text(encoding="utf-8") == (
        "# existing settings\n"
        "EVO_CLIENT_ID=new-client\n"
        "MCP_TOOL_FILTER=all\n"
        "MCP_HTTP_PORT=5000\n"
    )


def test_get_http_env_from_dotenv_requires_complete_http_settings(tmp_path, capsys):
    """Given incomplete HTTP config, when loading server env, then the helper returns None."""
    setup_mcp = _load_setup_mcp_module()

    (tmp_path / ".env").write_text("MCP_TRANSPORT=http\nMCP_HTTP_HOST=localhost\n", encoding="utf-8")

    result = setup_mcp.get_http_env_from_dotenv(tmp_path)

    assert result is None
    assert "Missing required values in .env" in capsys.readouterr().out


def test_resolve_command_path_expands_project_relative_script(tmp_path):
    """Given a relative command path, when resolved, then it is anchored to the project directory."""
    setup_mcp = _load_setup_mcp_module()

    assert setup_mcp.resolve_command_path("./src/mcp_tools.py", tmp_path) == str(
        (tmp_path / "src" / "mcp_tools.py").resolve()
    )


def test_build_config_entry_builds_expected_cursor_and_vscode_shapes():
    """Given client and protocol combinations, when building config entries, then the expected JSON shape is produced."""
    setup_mcp = _load_setup_mcp_module()

    cursor_client = setup_mcp.ClientChoice("Cursor", "cursor", "Cursor")
    vscode_client = setup_mcp.ClientChoice("VS Code", "vscode", "Code")

    cursor_key, cursor_entry = setup_mcp.build_config_entry(
        cursor_client,
        "stdio",
        "/venv/bin/python",
        "/repo/src/mcp_tools.py",
        {},
    )
    vscode_key, vscode_entry = setup_mcp.build_config_entry(
        vscode_client,
        "http",
        "/venv/bin/python",
        "/repo/src/mcp_tools.py",
        {"MCP_HTTP_HOST": "127.0.0.1", "MCP_HTTP_PORT": "9000"},
    )

    assert cursor_key == "mcpServers"
    assert cursor_entry == {"command": "/venv/bin/python", "args": ["/repo/src/mcp_tools.py"]}
    assert vscode_key == "servers"
    assert vscode_entry == {"type": "http", "url": "http://127.0.0.1:9000/mcp"}


def test_get_vscode_config_dir_prefers_wsl_agent_folder(tmp_path, monkeypatch):
    """Given a WSL environment, when resolving the VS Code config dir, then the VS Code server path wins over Windows fallback."""
    setup_mcp = _load_setup_mcp_module()

    agent_folder = tmp_path / "agent"
    (agent_folder / "data").mkdir(parents=True)
    win_home = tmp_path / "windows-home"
    (win_home / "AppData" / "Roaming" / "Code" / "User").mkdir(parents=True)

    monkeypatch.setattr(setup_mcp.platform, "system", lambda: "Linux")
    monkeypatch.setenv("WSL_INTEROP", "1")
    monkeypatch.setenv("VSCODE_AGENT_FOLDER", str(agent_folder))
    monkeypatch.setenv("WIN_HOME", str(win_home))

    result = setup_mcp.get_vscode_config_dir("Code")

    assert result == agent_folder / "data" / "User"


def test_setup_mcp_config_accepts_empty_existing_json_file(tmp_path, monkeypatch):
    """Given an empty existing mcp.json, when setup writes config, then it treats the file as an empty object and writes evo-mcp settings."""
    setup_mcp = _load_setup_mcp_module()

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    config_file = config_dir / "mcp.json"
    config_file.write_text("   \n", encoding="utf-8")

    monkeypatch.setattr(setup_mcp, "get_config_dir", lambda client: config_dir)
    monkeypatch.setattr(setup_mcp, "get_python_executable", lambda: "/current/python")
    monkeypatch.setattr(setup_mcp, "choose_python_executable", lambda default: "/chosen/python")
    monkeypatch.setattr(setup_mcp, "start_http_server", lambda *args, **kwargs: pytest.fail("start_http_server should not be called for stdio"))

    client = setup_mcp.ClientChoice("VS Code", "vscode", "Code")
    setup_mcp.setup_mcp_config(
        client=client,
        protocol="stdio",
        env_values={"MCP_TOOL_FILTER": "all"},
        start_server_now=False,
    )

    written = json.loads(config_file.read_text(encoding="utf-8"))
    assert written == {
        "servers": {
            "evo-mcp": {
                "type": "stdio",
                "command": "/chosen/python",
                "args": [str(SCRIPT_PATH.parent.parent / "src" / "mcp_tools.py")],
            }
        }
    }
