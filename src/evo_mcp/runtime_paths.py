# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Runtime filesystem locations for writable state."""

from __future__ import annotations

import os
from pathlib import Path


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser() if value else default


def get_state_dir() -> Path:
    return _path_from_env("EVO_MCP_STATE_DIR", Path.home() / ".local" / "share" / "evo-mcp")


def get_cache_dir() -> Path:
    return _path_from_env("EVO_MCP_CACHE_DIR", get_state_dir() / "cache")


def get_session_cache_dir(session_id: str) -> Path:
    return get_cache_dir() / "sessions" / session_id


def get_debug_log_path() -> Path:
    return _path_from_env("EVO_MCP_DEBUG_LOG_PATH", get_state_dir() / "logs" / "mcp_tools_debug.log")
