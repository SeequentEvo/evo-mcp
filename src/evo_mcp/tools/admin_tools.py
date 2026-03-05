# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for workspace management operations.
"""

from uuid import UUID
from datetime import datetime
from fastmcp import Context
from fastmcp.utilities.logging import get_logger


from evo_mcp.context import evo_context, ensure_initialized
from evo_mcp.utils.evo_data_utils import extract_data_references, copy_object_data

logger = get_logger(__name__)


def register_admin_tools(mcp):
    """Register all workspace-related tools with the FastMCP server."""
    
    @mcp.tool()
    async def create_workspace(
        name: str,
        description: str = "",
        labels: list[str] = [],
        ctx: Context | None = None,
    ) -> dict:
        """Create a new workspace.
        
        Args:
            name: Workspace name
            description: Workspace description
            labels: Workspace labels (optional list)
        """
        if ctx:
            await ctx.info(
                "Creating workspace",
                extra={"workspace_name": name, "has_description": bool(description), "label_count": len(labels or [])},
            )
        await ensure_initialized()
        
        workspace = await evo_context.workspace_client.create_workspace(
            name=name,
            description=description,
            labels=labels or []
        )
        
        result = {
            "id": str(workspace.id),
            "name": workspace.display_name,
            "description": workspace.description,
            "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        }

        if ctx:
            await ctx.info("Workspace created", extra={"workspace_id": result["id"], "workspace_name": result["name"]})

        return result

    @mcp.tool()
    async def get_workspace_summary(
        workspace_id: str,
        ctx: Context | None = None,
    ) -> dict:
        """Get summary statistics for a workspace (object counts by type).
        
        Args:
            workspace_id: Workspace UUID
        """
        if ctx:
            await ctx.info("Getting workspace summary", extra={"workspace_id": workspace_id})
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        
        # Get all objects
        all_objects = await object_client.list_all_objects()
        
        # Count by schema type
        schema_counts = {}
        for obj in all_objects:
            schema = obj.schema_id.sub_classification
            schema_counts[schema] = schema_counts.get(schema, 0) + 1
        
        result = {
            "workspace_id": str(workspace_id),
            "total_objects": len(all_objects),
            "objects_by_schema": schema_counts,
        }

        if ctx:
            await ctx.info("Workspace summary complete", extra={"total_objects": result["total_objects"]})

        return result

    @mcp.tool()
    async def create_workspace_snapshot(
        workspace_id: str,
        snapshot_name: str = "",
        include_data_blobs: bool = False,
        ctx: Context | None = None,
    ) -> dict:
        """Create a snapshot of all objects and their current versions in a workspace.
        
        Args:
            workspace_id: Workspace UUID to snapshot
            snapshot_name: Optional name for the snapshot (defaults to timestamp)
            include_data_blobs: If True, include data blob references (increases size)
            
        Returns:
            Snapshot metadata and object version information
        """
        if ctx:
            await ctx.info(
                "Creating workspace snapshot",
                extra={
                    "workspace_id": workspace_id,
                    "snapshot_name": snapshot_name or None,
                    "include_data_blobs": include_data_blobs,
                },
            )
            await ctx.report_progress(progress=5, total=100)

        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        workspace = await evo_context.workspace_client.get_workspace(UUID(workspace_id))
        
        # Get all objects
        all_objects = await object_client.list_all_objects()
        if ctx:
            await ctx.report_progress(progress=20, total=100)
        
        # Create snapshot
        timestamp = datetime.utcnow().isoformat()
        snapshot_name = snapshot_name or f"snapshot_{timestamp}"
        
        objects_snapshot = []
        
        total_objects = len(all_objects)
        for i, obj in enumerate(all_objects):
            obj_info = {
                "id": str(obj.id),
                "name": obj.name,
                "path": obj.path,
                "schema_id": obj.schema_id.sub_classification,
                "version_id": obj.version_id,
                "created_at": obj.created_at.isoformat() if obj.created_at else None,
                # "updated_at": obj.updated_at.isoformat() if obj.updated_at else None
            }
            
            if include_data_blobs:
                try:
                    downloaded_obj = await object_client.download_object_by_id(obj.id, version=obj.version_id)
                    data_refs = extract_data_references(downloaded_obj.as_dict())
                    obj_info["data_blobs"] = data_refs
                except Exception:
                    obj_info["data_blobs"] = []
            
            objects_snapshot.append(obj_info)
            if ctx and total_objects > 0:
                progress = 20 + int(((i + 1) / total_objects) * 75)
                await ctx.report_progress(progress=progress, total=100)

        if ctx:
            await ctx.report_progress(progress=100, total=100)
        
        snapshot = {
            "snapshot_name": snapshot_name,
            "snapshot_timestamp": timestamp,
            "workspace_id": workspace_id,
            "workspace_name": workspace.display_name,
            "workspace_description": workspace.description,
            "object_count": len(objects_snapshot),
            "objects": objects_snapshot
        }
        
        return {
            "snapshot": snapshot,
            "summary": {
                "snapshot_name": snapshot_name,
                "timestamp": timestamp,
                "workspace_id": workspace_id,
                "total_objects": len(objects_snapshot),
                "note_to_user": "Store this snapshot data to restore later using evo_restore_workspace_snapshot",
                "note_to_agent": "Display the full snapshot in your response."
            }
        }

    @mcp.tool()
    async def workspace_copy_object(
        source_workspace_id: str,
        target_workspace_id: str,
        object_id: str,
        version: str = "",
        ctx: Context | None = None,
    ) -> dict:
        """Copy a single object from one workspace to another, including data blobs.
        
        Args:
            source_workspace_id: Source workspace UUID
            target_workspace_id: Target workspace UUID
            object_id: Object UUID to copy
            version: Specific version ID (optional)
        """
        if ctx:
            await ctx.info(
                "Copying object between workspaces",
                extra={
                    "source_workspace_id": source_workspace_id,
                    "target_workspace_id": target_workspace_id,
                    "object_id": object_id,
                    "version": version or None,
                },
            )
            await ctx.report_progress(progress=5, total=100)

        await ensure_initialized()
        source_client = await evo_context.get_object_client(UUID(source_workspace_id))
        target_client = await evo_context.get_object_client(UUID(target_workspace_id))
        
        # Download source object
        source_object = await source_client.download_object_by_id(UUID(object_id), version=version if version else None)
        if ctx:
            await ctx.report_progress(progress=30, total=100)
        
        # Extract and copy data blobs
        data_identifiers = extract_data_references(source_object.as_dict())
        if data_identifiers:
            await copy_object_data(
                source_client,
                target_client,
                source_object,
                data_identifiers,
                evo_context.connector
            )
        if ctx:
            await ctx.report_progress(progress=75, total=100)
        
        # Create object in target workspace
        object_dict = source_object.as_dict()
        object_dict["uuid"] = None
        
        new_metadata = await target_client.create_geoscience_object(
            source_object.metadata.path,
            object_dict
        )
        if ctx:
            await ctx.report_progress(progress=100, total=100)
        
        return {
            "id": str(new_metadata.id),
            "name": new_metadata.name,
            "path": new_metadata.path,
            "version_id": new_metadata.version_id,
            "data_blobs_copied": len(data_identifiers),
        }

    @mcp.tool()
    async def workspace_duplicate_workspace(
        source_workspace_id: str,
        target_name: str,
        target_description: str = "",
        schema_filter: list[str] = [],
        name_filter: list[str] = [],
        ctx: Context | None = None,
    ) -> dict:
        """Duplicate entire workspace (all objects and data blobs).
        
        Args:
            source_workspace_id: Source workspace UUID
            target_name: Target workspace name
            target_description: Target workspace description
            schema_filter: Filter by object types (optional list)
            name_filter: Filter by object names (optional list)
        """
        if ctx:
            await ctx.info(
                "Duplicating workspace",
                extra={
                    "source_workspace_id": source_workspace_id,
                    "target_name": target_name,
                    "schema_filter_count": len(schema_filter),
                    "name_filter_count": len(name_filter),
                },
            )
            await ctx.report_progress(progress=5, total=100)

        await ensure_initialized()
        
        # Create target workspace
        target_workspace = await evo_context.workspace_client.create_workspace(
            name=target_name,
            description=target_description or "Duplicated workspace"
        )
        if ctx:
            await ctx.report_progress(progress=15, total=100)
        
        source_client = await evo_context.get_object_client(UUID(source_workspace_id))
        target_client = await evo_context.get_object_client(target_workspace.id)
        
        # Get all objects from source
        all_objects = await source_client.list_all_objects()
        
        # Apply filters
        filtered_objects = [
            obj for obj in all_objects
            if (not schema_filter or obj.schema_id.sub_classification in schema_filter) and
               (not name_filter or obj.name in name_filter)
        ]
        total_objects = len(filtered_objects)

        if ctx:
            await ctx.info(
                "Workspace duplication object selection complete",
                extra={"selected_objects": total_objects, "source_total_objects": len(all_objects)},
            )
            if total_objects == 0:
                await ctx.report_progress(progress=100, total=100)
        
        # Track progress
        copied_count = 0
        failed_count = 0
        cloned_data_ids = set()
        
        for i, obj in enumerate(filtered_objects):
            try:
                # Download object
                source_object = await source_client.download_object_by_id(
                    obj.id,
                    version=obj.version_id
                )
                
                # Extract and copy new data blobs
                data_identifiers = extract_data_references(source_object.as_dict())
                new_data_identifiers = [d for d in data_identifiers if d not in cloned_data_ids]
                
                if new_data_identifiers:
                    await copy_object_data(
                        source_client,
                        target_client,
                        source_object,
                        new_data_identifiers,
                        evo_context.connector
                    )
                    cloned_data_ids.update(new_data_identifiers)
                
                # Create object in target
                object_dict = source_object.as_dict()
                object_dict["uuid"] = None
                
                await target_client.create_geoscience_object(
                    source_object.metadata.path,
                    object_dict
                )
                
                copied_count += 1
                if ctx and total_objects > 0:
                    progress = 20 + int(((i + 1) / total_objects) * 75)
                    await ctx.report_progress(progress=progress, total=100)
                
            except Exception as e:
                failed_count += 1
                if ctx:
                    await ctx.warning(
                        "Failed to copy object while duplicating workspace",
                        extra={"object_id": str(obj.id), "object_name": obj.name, "error": str(e)},
                    )
                logger.exception("Failed to copy object during workspace duplication")
                # Continue with next object

        if ctx:
            await ctx.report_progress(progress=100, total=100)
        
        return {
            "target_workspace_id": str(target_workspace.id),
            "target_workspace_name": target_workspace.display_name,
            "objects_copied": copied_count,
            "objects_failed": failed_count,
            "data_blobs_copied": len(cloned_data_ids),
        }
