# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for object management operations.
"""

import json
from uuid import UUID
from fastmcp import Context
from fastmcp.utilities.logging import get_logger

from evo_mcp.context import evo_context, ensure_initialized
from evo_mcp.utils.evo_data_utils import extract_data_references

logger = get_logger(__name__)


def register_data_tools(mcp):
    """Register all object-related tools with the FastMCP server."""
    
    @mcp.tool()
    async def create_object(
        workspace_id: str,
        path: str,
        object_dict: dict,
        ctx: Context | None = None,
    ) -> dict:
        """Create a new object in a workspace.
        
        Args:
            workspace_id: Workspace UUID
            path: Object path
            object_dict: Object definition as JSON/dict
        """
        if ctx:
            await ctx.info("Creating object", extra={"workspace_id": workspace_id, "path": path})
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        
        # Ensure no UUID is set for new objects
        if isinstance(object_dict, str):
            object_dict = json.loads(object_dict)
        object_dict["uuid"] = None
        
        metadata = await object_client.create_geoscience_object(path, object_dict)
        
        result = {
            "id": str(metadata.id),
            "name": metadata.name,
            "path": metadata.path,
            "version_id": metadata.version_id,
            "created_at": metadata.created_at.isoformat() if metadata.created_at else None,
        }

        if ctx:
            await ctx.info("Object created", extra={"object_id": result["id"], "path": result["path"]})

        return result
    
    @mcp.tool()
    async def get_object_content(
        workspace_id: str,
        object_id: str = "",
        object_path: str = "",
        version: str = "",
        ctx: Context | None = None,
    ) -> dict:
        """Download complete object definition as JSON.
        
        Args:
            workspace_id: Workspace UUID
            object_id: Object UUID (provide either this or object_path)
            object_path: Object path
            version: Specific version ID
        """
        if ctx:
            await ctx.info(
                "Getting object content",
                extra={
                    "workspace_id": workspace_id,
                    "object_id": object_id or None,
                    "object_path": object_path or None,
                    "version": version or None,
                },
            )
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        
        if object_id:
            obj = await object_client.download_object_by_id(UUID(object_id), version=version if version else None)
        elif object_path:
            obj = await object_client.download_object_by_path(object_path, version=version if version else None)
        else:
            raise ValueError("Either object_id or object_path must be provided")
        
        result = {
            "metadata": {
                "id": str(obj.metadata.id),
                "name": obj.metadata.name,
                "path": obj.metadata.path,
                "schema_id": obj.metadata.schema_id.sub_classification,
                "version_id": obj.metadata.version_id,
            },
            "content": obj.as_dict()
        }

        if ctx:
            await ctx.info("Object content fetched", extra={"object_id": result["metadata"]["id"]})

        return result


    @mcp.tool()
    async def get_object_versions(
        workspace_id: str,
        object_id: str = "",
        object_path: str = "",
        ctx: Context | None = None,
    ) -> list[dict]:
        """List all versions of an object.
        
        Args:
            workspace_id: Workspace UUID
            object_id: Object UUID (provide either this or object_path)
            object_path: Object path (provide either this or object_id)
        """
        if ctx:
            await ctx.info(
                "Listing object versions",
                extra={"workspace_id": workspace_id, "object_id": object_id or None, "object_path": object_path or None},
            )
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        
        if object_id:
            versions = await object_client.list_versions_by_id(UUID(object_id))
        elif object_path:
            versions = await object_client.list_versions_by_path(object_path)
        else:
            raise ValueError("Either object_id or object_path must be provided")
        
        result = [
            {
                "version_id": v.version_id,
                "created_at": v.created_at.isoformat() if v.created_at else None,
                "created_by": str(v.created_by.id) if v.created_by else None,
            }
            for v in versions
        ]

        if ctx:
            await ctx.info("Object versions listed", extra={"returned_count": len(result)})

        return result

    @mcp.tool()
    async def extract_data_references(
        workspace_id: str,
        object_id: str,
        version: str = "",
        ctx: Context | None = None,
    ) -> list[str]:
        """Extract all data blob references from an object.
        
        Args:
            workspace_id: Workspace UUID
            object_id: Object UUID
            version: Specific version ID (optional)
        """
        if ctx:
            await ctx.info(
                "Extracting data references",
                extra={"workspace_id": workspace_id, "object_id": object_id, "version": version or None},
            )
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        
        obj = await object_client.download_object_by_id(UUID(object_id), version=version if version else None)
        data_refs = extract_data_references(obj.as_dict())

        if ctx:
            await ctx.info("Data references extracted", extra={"reference_count": len(data_refs)})
        
        return data_refs