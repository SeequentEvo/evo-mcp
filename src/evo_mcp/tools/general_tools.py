"""
MCP tools for general operations (health checks, object CRUD, etc).
"""

import logging
from uuid import UUID

from fastmcp import Context

from evo_mcp.context import evo_context, ensure_initialized

# Set up logging to file for debugging
logging.basicConfig(
    filename='mcp_tools_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def register_general_tools(mcp):
    """Register all general tools with the FastMCP server."""
    
    @mcp.tool()
    async def workspace_health_check(workspace_id: str = "") -> dict:
        """Check health status of Evo services.
        
        Args:
            workspace_id: Workspace UUID to check object service (optional)
        """
        results = {}
        
        if evo_context.workspace_client:
            workspace_health = await evo_context.workspace_client.get_service_health()
            results["workspace_service"] = {
                "service": workspace_health.service,
                "status": workspace_health.status,
            }
        
        if workspace_id:
            await ensure_initialized()
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            object_health = await object_client.get_service_health()
            results["object_service"] = {
                "service": object_health.service,
                "status": object_health.status,
            }
        
        return results

    @mcp.tool()
    async def list_workspaces(
        name: str = "",
        deleted: bool = False,
        limit: int = 50
    ) -> list[dict]:
        """List workspaces with optional filtering by name or deleted status.
        
        Args:
            name: Filter by workspace name (leave empty for no filter)
            deleted: Include deleted workspaces
            limit: Maximum number of results
        """
        await ensure_initialized()
        
        workspaces = await evo_context.workspace_client.list_workspaces(
            name=name if name else None,
            deleted=deleted,
            limit=limit
        )
        
        return [
            {
                "id": str(ws.id),
                "name": ws.display_name,
                "description": ws.description,
                "user_role": ws.user_role.name if ws.user_role else None,
                "created_at": ws.created_at.isoformat() if ws.created_at else None,
                "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
            }
            for ws in workspaces.items()
        ]

    @mcp.tool()
    async def get_workspace(
        workspace_id: str = "",
        workspace_name: str = ""
    ) -> dict:
        """Get workspace details by ID or name.
        
        Args:
            workspace_id: Workspace UUID (provide either this or workspace_name)
            workspace_name: Workspace name (provide either this or workspace_id)
        """
        await ensure_initialized()
        
        if workspace_id:
            workspace = await evo_context.workspace_client.get_workspace(UUID(workspace_id))
        elif workspace_name:
            workspaces = await evo_context.workspace_client.list_workspaces(name=workspace_name)
            matching = [ws for ws in workspaces.items() if ws.display_name == workspace_name]
            if not matching:
                raise ValueError(f"Workspace '{workspace_name}' not found")
            workspace = matching[0]
        else:
            raise ValueError("Either workspace_id or workspace_name must be provided")
        
        return {
            "id": str(workspace.id),
            "name": workspace.display_name,
            "description": workspace.description,
            "user_role": workspace.user_role.name if workspace.user_role else None,
            "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
            "updated_at": workspace.updated_at.isoformat() if workspace.updated_at else None,
            "created_by": workspace.created_by.id if workspace.created_by else None,
            "default_coordinate_system": workspace.default_coordinate_system,
            "labels": workspace.labels,
        }
    
    @mcp.tool()
    async def list_objects(
        workspace_id: str,
        schema_id: str = "",
        deleted: bool = False,
        limit: int = 100
    ) -> list[dict]:
        """List objects in a workspace with optional filtering.
        
        Args:
            workspace_id: Workspace UUID
            schema_id: Filter by schema/object type (leave empty for no filter)
            deleted: Include deleted objects
            limit: Maximum number of results
        """
        logger.info(f"evo_list_objects called with workspace_id={workspace_id}, schema_id={schema_id}")
        
        try:
            logger.debug("Calling ensure_initialized()")
            await ensure_initialized()
            logger.debug("ensure_initialized() completed successfully")
            
            logger.debug(f"Getting object client for workspace {workspace_id}")
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            logger.debug(f"Got object_client: {object_client}")
            
            service_health = await object_client.get_service_health()
            status = service_health.raise_for_status()
            logger.debug("Object client status:", status)
            
            logger.debug("Calling list_objects()")
            objects = await object_client.list_objects(
                schema_id=None, # [schema_id] if schema_id else None,
                deleted=deleted,
                limit=limit
            )

            logger.debug(f"list_objects() returned {len(objects.items())} objects")
            
            result = [
                {
                    "id": str(obj.id),
                    "name": obj.name,
                    "path": obj.path,
                    "schema_id": obj.schema_id.sub_classification,
                    "version_id": obj.version_id,
                    "created_at": obj.created_at.isoformat() if obj.created_at else None,
                    # "updated_at": obj.updated_at.isoformat() if obj.updated_at else None,
                }
                for obj in objects.items()
            ]
            logger.info(f"evo_list_objects completed successfully with {len(result)} objects")
            return result
            
        except Exception as e:
            logger.error(f"Error in evo_list_objects: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    @mcp.tool()
    async def get_object(
        workspace_id: str,
        object_id: str = "",
        object_path: str = "",
        version: str = ""
    ) -> dict:
        """Get object metadata by ID or path.
        
        Args:
            workspace_id: Workspace UUID
            object_id: Object UUID (provide either this or object_path)
            object_path: Object path (provide either this or object_id)
            version: Specific version ID (optional)
        """
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        
        if object_id:
            obj = await object_client.download_object_by_id(UUID(object_id), version=version)
        elif object_path:
            obj = await object_client.download_object_by_path(object_path, version=version)
        else:
            raise ValueError("Either object_id or object_path must be provided")
        
        return {
            "id": str(obj.metadata.id),
            "name": obj.metadata.name,
            "path": obj.metadata.path,
            "schema_id": obj.metadata.schema_id.sub_classification,
            "version_id": obj.metadata.version_id,
            "created_at": obj.metadata.created_at.isoformat() if obj.metadata.created_at else None,
            #"updated_at": obj.metadata.updated_at.isoformat() if obj.metadata.updated_at else None,
        }


    @mcp.tool()
    async def list_my_instances(
        ctx: Context,
    ) -> list[dict]:
        """List instances the user has access to."""
        await ensure_initialized()

        if evo_context.org_id:
            await ctx.info(f"Selected instance ID {evo_context.org_id}")
        instances = await evo_context.discovery_client.list_organizations()
        return instances

    @mcp.tool()
    async def select_instance(
        instance_name: str | None = None,
        instance_id: UUID | None = None,
    ) -> dict | None:
        """Select an instance to connect to.

        Subsequent tool invocations like "list workspaces" will act on this
        Evo Instance.

        Args:
            instance_id: Instance UUID (provide either this or instance_name)
            instance_name: Instance name (provide either this or instance_id)

        Returns:
            The selected instance or `None` if no instance was matched from the
            arguments.
        """
        await ensure_initialized()

        instances = await evo_context.discovery_client.list_organizations()
        for instance in instances:
            if instance.id == instance_id or instance.display_name == instance_name:
                evo_context.org_id = instance.id
                evo_context.hub_url = instance.hubs[0].url
                evo_context.save_variables_to_cache()
                return instance

        return None
