# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for object visualisation workflows."""

from __future__ import annotations

import asyncio
from typing import Any

from evo.objects.typed import object_from_uuid
from evo.widgets import get_portal_url, get_viewer_url

from evo_mcp.utils.tool_support import (
    get_workspace_context,
    get_workspace_environment,
    schema_label,
)


def register_visualisation_tools(mcp) -> None:
    """Register visualisation tools with the FastMCP server."""

    @mcp.tool()
    async def viewer_generate_multi_object_links(
        workspace_id: str,
        object_ids: list[str],
    ) -> dict[str, Any]:
        """Generate portal and viewer links for an explicit user-supplied object list."""
        if len(object_ids) == 0:
            raise ValueError("object_ids must contain at least one object ID.")

        context = await get_workspace_context(workspace_id)
        environment = await get_workspace_environment(workspace_id)
        unique_requested_ids = list(dict.fromkeys(object_ids))
        try:
            resolved_objects = await asyncio.gather(
                *(
                    object_from_uuid(context, object_id)
                    for object_id in unique_requested_ids
                )
            )
        except Exception as exc:
            raise ValueError(
                f"Could not resolve one or more object IDs for viewer-link generation: {exc}"
            ) from exc

        unique_ids = list(
            dict.fromkeys(str(obj.metadata.id) for obj in resolved_objects)
        )
        viewer_url = get_viewer_url(
            org_id=str(environment.org_id),
            workspace_id=str(environment.workspace_id),
            object_ids=unique_ids,
            hub_url=environment.hub_url,
        )

        return {
            "status": "success",
            "viewer_url": viewer_url,
            "object_count": len(unique_ids),
            "objects": [
                {
                    "id": str(obj.metadata.id),
                    "name": getattr(obj, "name", str(obj.metadata.id)),
                    "schema_id": schema_label(obj),
                    "portal_url": get_portal_url(
                        org_id=str(environment.org_id),
                        workspace_id=str(environment.workspace_id),
                        object_id=str(obj.metadata.id),
                        hub_url=environment.hub_url,
                    ),
                }
                for obj in resolved_objects
            ],
        }
