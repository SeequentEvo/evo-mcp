"""
MCP tools for workspace management operations.
"""

from uuid import UUID
from datetime import datetime


from evo_mcp.context import evo_context, ensure_initialized
from evo_mcp.utils.evo_data_utils import extract_data_references, copy_object_data


def register_admin_tools(mcp):
    """Register all workspace-related tools with the FastMCP server."""
    
    @mcp.tool()
    async def create_workspace(
        name: str,
        description: str = "",
        labels: list[str] = []
    ) -> dict:
        """Create a new workspace.
        
        Args:
            name: Workspace name
            description: Workspace description
            labels: Workspace labels (optional list)
        """
        await ensure_initialized()
        
        workspace = await evo_context.workspace_client.create_workspace(
            name=name,
            description=description,
            labels=labels or []
        )
        
        return {
            "id": str(workspace.id),
            "name": workspace.display_name,
            "description": workspace.description,
            "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        }

    @mcp.tool()
    async def get_workspace_summary(workspace_id: str) -> dict:
        """Get summary statistics for a workspace (object counts by type).
        
        Args:
            workspace_id: Workspace UUID
        """
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        
        # Get all objects
        all_objects = await object_client.list_all_objects()
        
        # Count by schema type
        schema_counts = {}
        for obj in all_objects:
            schema = obj.schema_id.sub_classification
            schema_counts[schema] = schema_counts.get(schema, 0) + 1
        
        return {
            "workspace_id": str(workspace_id),
            "total_objects": len(all_objects),
            "objects_by_schema": schema_counts,
        }

    @mcp.tool()
    async def create_workspace_snapshot(
        workspace_id: str,
        snapshot_name: str = "",
        include_data_blobs: bool = False
    ) -> dict:
        """Create a snapshot of all objects and their current versions in a workspace.
        
        Args:
            workspace_id: Workspace UUID to snapshot
            snapshot_name: Optional name for the snapshot (defaults to timestamp)
            include_data_blobs: If True, include data blob references (increases size)
            
        Returns:
            Snapshot metadata and object version information
        """
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        workspace = await evo_context.workspace_client.get_workspace(UUID(workspace_id))
        
        # Get all objects
        all_objects = await object_client.list_all_objects()
        
        # Create snapshot
        timestamp = datetime.utcnow().isoformat()
        snapshot_name = snapshot_name or f"snapshot_{timestamp}"
        
        objects_snapshot = []
        
        for obj in all_objects:
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
        version: str = ""
    ) -> dict:
        """Copy a single object from one workspace to another, including data blobs.
        
        Args:
            source_workspace_id: Source workspace UUID
            target_workspace_id: Target workspace UUID
            object_id: Object UUID to copy
            version: Specific version ID (optional)
        """
        await ensure_initialized()
        source_client = await evo_context.get_object_client(UUID(source_workspace_id))
        target_client = await evo_context.get_object_client(UUID(target_workspace_id))
        
        # Download source object
        source_object = await source_client.download_object_by_id(UUID(object_id), version=version if version else None)
        
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
        
        # Create object in target workspace
        object_dict = source_object.as_dict()
        object_dict["uuid"] = None
        
        new_metadata = await target_client.create_geoscience_object(
            source_object.metadata.path,
            object_dict
        )
        
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
        name_filter: list[str] = []
    ) -> dict:
        """Duplicate entire workspace (all objects and data blobs).
        
        Args:
            source_workspace_id: Source workspace UUID
            target_name: Target workspace name
            target_description: Target workspace description
            schema_filter: Filter by object types (optional list)
            name_filter: Filter by object names (optional list)
        """
        await ensure_initialized()
        
        # Create target workspace
        target_workspace = await evo_context.workspace_client.create_workspace(
            name=target_name,
            description=target_description or "Duplicated workspace"
        )
        
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
        
        # Track progress
        copied_count = 0
        failed_count = 0
        cloned_data_ids = set()
        
        for obj in filtered_objects:
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
                
            except Exception:
                failed_count += 1
                # Continue with next object
        
        return {
            "target_workspace_id": str(target_workspace.id),
            "target_workspace_name": target_workspace.display_name,
            "objects_copied": copied_count,
            "objects_failed": failed_count,
            "data_blobs_copied": len(cloned_data_ids),
        }
