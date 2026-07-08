# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Self-contained PoC MCP server with mock Evo-flavored tools.

The tools return canned data so reviewers can explore the three tool-exposure
strategies (``none`` / ``tool-search`` / ``code-mode``) WITHOUT Evo credentials
or network access. The point of the PoC is to observe *what the model sees* and
*how it reaches the tools*, not to hit real Evo APIs.

Run standalone (strategy from env)::

    MCP_TOOL_STRATEGY=code-mode uv run python src/poc/demo_server.py

Or build in-process for the notebook::

    from demo_server import build_demo_server
    mcp = build_demo_server("tool-search")
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make this folder importable (for `tool_strategy`) and the evo_mcp package importable
# (for the notebook's live-server section, which registers the real Evo tools). This lets
# the PoC run from any working directory. Layout: <repo>/src/poc/<this file>.
_HERE = Path(__file__).resolve().parent
_SRC = _HERE.parent  # <repo>/src
for _p in (_HERE, _SRC):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from fastmcp import FastMCP  # noqa: E402  (import follows the sys.path shim above)
from tool_strategy import (  # noqa: E402  (co-located strategy factory, shared with the real server)
    SearchEngine,
    ToolStrategy,
    apply_strategy,
)

# ── Canned data ────────────────────────────────────────────────────────────────

_WORKSPACES = [
    {"id": "ws-001", "name": "Copper Ridge", "objects": 42},
    {"id": "ws-002", "name": "Gold Valley", "objects": 17},
    {"id": "ws-003", "name": "Iron Basin", "objects": 88},
]

_OBJECTS = {
    "ws-001": [
        {"id": "obj-a", "name": "collars", "schema": "downhole-collection", "size": 1200},
        {"id": "obj-b", "name": "topography", "schema": "pointset", "size": 98000},
        {"id": "obj-c", "name": "cu_grade", "schema": "pointset", "size": 45000},
    ],
    "ws-002": [
        {"id": "obj-d", "name": "faults", "schema": "line-segments", "size": 300},
    ],
    "ws-003": [
        {"id": "obj-e", "name": "block_model", "schema": "regular-block-model", "size": 5_000_000},
    ],
}

_USERS = [
    {"id": "u-1", "email": "geo@example.com", "role": "editor"},
    {"id": "u-2", "email": "admin@example.com", "role": "owner"},
]


def register_demo_tools(mcp: FastMCP) -> None:
    """Register a representative spread of read + write + admin tools.

    Tags (``read`` / ``write`` / ``admin`` / ``compute``) mirror how the real
    server could tag tools so a strategy can hide destructive tools from the
    code/search path via a Visibility transform.
    """

    # ── Read tools ──────────────────────────────────────────────────────────
    @mcp.tool(tags={"read"})
    def list_workspaces() -> list[dict]:
        """List all workspaces the caller can access."""
        return _WORKSPACES

    @mcp.tool(tags={"read"})
    def get_workspace(workspace_id: str) -> dict:
        """Get details for a single workspace by id."""
        for ws in _WORKSPACES:
            if ws["id"] == workspace_id:
                return ws
        raise ValueError(f"workspace {workspace_id!r} not found")

    @mcp.tool(tags={"read"})
    def list_objects(workspace_id: str, schema: str = "") -> list[dict]:
        """List geoscience objects in a workspace, optionally filtered by schema."""
        objs = _OBJECTS.get(workspace_id, [])
        if schema:
            objs = [o for o in objs if o["schema"] == schema]
        return objs

    @mcp.tool(tags={"read"})
    def get_object(workspace_id: str, object_id: str) -> dict:
        """Get metadata for a single object."""
        for o in _OBJECTS.get(workspace_id, []):
            if o["id"] == object_id:
                return o
        raise ValueError(f"object {object_id!r} not found")

    @mcp.tool(tags={"read"})
    def get_object_versions(workspace_id: str, object_id: str) -> list[dict]:
        """List the version history of an object."""
        return [
            {"version": "v1", "created_at": "2026-01-02"},
            {"version": "v2", "created_at": "2026-03-15"},
        ]

    @mcp.tool(tags={"read"})
    def count_points(workspace_id: str, object_id: str) -> int:
        """Return the number of points in a pointset-like object."""
        for o in _OBJECTS.get(workspace_id, []):
            if o["id"] == object_id:
                return o["size"]
        raise ValueError(f"object {object_id!r} not found")

    @mcp.tool(tags={"read"})
    def list_users() -> list[dict]:
        """List users in the current instance."""
        return _USERS

    @mcp.tool(tags={"read"})
    def workspace_health_check() -> dict:
        """Report health of the workspace and object services."""
        return {"workspace_service": "ok", "object_service": "ok"}

    # ── Write tools ─────────────────────────────────────────────────────────
    @mcp.tool(tags={"write"})
    def create_workspace(name: str, description: str = "") -> dict:
        """Create a new workspace."""
        return {"id": "ws-new", "name": name, "description": description}

    @mcp.tool(tags={"write"})
    def create_pointset(workspace_id: str, name: str, points: list) -> dict:
        """Create a pointset object from a list of XYZ points."""
        return {"id": "obj-new", "name": name, "point_count": len(points)}

    @mcp.tool(tags={"write"})
    def upload_file(workspace_id: str, local_path: str, target_path: str = "") -> dict:
        """Upload a file into a workspace's file store."""
        return {"path": target_path or local_path, "status": "uploaded"}

    # ── Compute tools ───────────────────────────────────────────────────────
    @mcp.tool(tags={"compute"})
    def kriging_run(workspace_id: str, object_id: str, variogram: dict) -> dict:
        """Run a kriging estimation job and return a job handle."""
        return {"job_id": "job-123", "status": "queued"}

    # ── Admin / destructive tools ───────────────────────────────────────────
    @mcp.tool(tags={"admin", "destructive"})
    def delete_object(workspace_id: str, object_id: str) -> dict:
        """Permanently delete an object. Destructive."""
        return {"id": object_id, "deleted": True}

    @mcp.tool(tags={"admin", "destructive"})
    def remove_user(user_id: str) -> dict:
        """Remove a user from the instance. Destructive."""
        return {"id": user_id, "removed": True}

    @mcp.tool(tags={"admin"})
    def update_user_role(user_id: str, role: str) -> dict:
        """Change a user's role in the instance."""
        return {"id": user_id, "role": role}


def build_demo_server(
    strategy: ToolStrategy | str | None = None,
    *,
    search_engine: SearchEngine | str | None = None,
    max_results: int = 5,
    always_visible: list[str] | None = None,
) -> FastMCP:
    """Build a demo server with tools registered and a strategy applied.

    Args:
        strategy: ``none`` / ``tool-search`` / ``code-mode``. Defaults to the
            ``MCP_TOOL_STRATEGY`` env var when ``None``.
        search_engine: ``bm25`` / ``regex`` for the tool-search strategy.
        max_results: Max results per search (tool-search only).
        always_visible: Tool names to keep pinned in ``list_tools``.
    """
    if isinstance(strategy, str):
        strategy = ToolStrategy(strategy)
    if isinstance(search_engine, str):
        search_engine = SearchEngine(search_engine)

    mcp = FastMCP("Evo MCP PoC")
    register_demo_tools(mcp)
    applied = apply_strategy(
        mcp,
        strategy,
        search_engine=search_engine,
        max_results=max_results,
        always_visible=always_visible,
    )
    mcp.instructions = f"Evo MCP PoC demo server (tool strategy: {applied.value})."
    return mcp


if __name__ == "__main__":
    # Strategy chosen from MCP_TOOL_STRATEGY / MCP_SEARCH_ENGINE env vars.
    build_demo_server().run()
