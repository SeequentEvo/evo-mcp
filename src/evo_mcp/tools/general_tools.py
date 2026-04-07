# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for general operations (health checks, object CRUD, etc).
"""

from uuid import UUID, uuid4

from fastmcp import Context
from fastmcp.utilities.logging import get_logger

from evo_mcp.context import evo_context, ensure_initialized
from evo_mcp.logging_utils import log_handled_failure, log_operation_event, operation_extra, result_with_operation_id

logger = get_logger(__name__)


def register_general_tools(mcp):
    """Register all general tools with the FastMCP server."""
    
    @mcp.tool()
    async def workspace_health_check(
        workspace_id: str = "",
        ctx: Context | None = None,
    ) -> dict:
        """Check health status of Evo services.
        
        Args:
            workspace_id: Workspace UUID to check object service (optional)
        """
        operation_id = str(uuid4())
        await log_operation_event(
            ctx,
            logger,
            "Running workspace health check",
            operation_id,
            workspace_id=workspace_id or None,
        )
        try:
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

            await log_operation_event(
                ctx,
                logger,
                "Workspace health check complete",
                operation_id,
                services=list(results.keys()),
            )
            return result_with_operation_id(operation_id, results)
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to run workspace health check",
                operation_id,
                e,
                workspace_id=workspace_id or None,
            )
            raise

    @mcp.tool()
    async def list_workspaces(
        name: str = "",
        deleted: bool = False,
        limit: int = 50,
        ctx: Context | None = None,
    ) -> list[dict]:
        """List workspaces with optional filtering by name or deleted status.
        
        Args:
            name: Filter by workspace name (leave empty for no filter)
            deleted: Include deleted workspaces
            limit: Maximum number of results
        """
        if limit <= 0:
            raise ValueError("limit must be greater than 0")

        operation_id = str(uuid4())

        await log_operation_event(
            ctx,
            logger,
            "Listing workspaces",
            operation_id,
            filter_name=name or None,
            deleted=deleted,
            limit=limit,
        )
        try:
            await ensure_initialized()

            requested_limit = limit
            max_page_size = 100
            remaining = requested_limit
            offset = 0
            workspace_items = []
            pages_fetched = 0

            # Workspace service enforces a maximum page size of 100.
            while remaining > 0:
                page_limit = min(max_page_size, remaining)
                workspaces_page = await evo_context.workspace_client.list_workspaces(
                    name=name if name else None,
                    deleted=deleted,
                    limit=page_limit,
                    offset=offset,
                )

                page_items = workspaces_page.items()
                if not page_items:
                    break

                workspace_items.extend(page_items)
                pages_fetched += 1

                fetched_count = len(page_items)
                remaining -= fetched_count
                offset += fetched_count

                if offset >= workspaces_page.total:
                    break

            if ctx and pages_fetched > 1:
                await ctx.debug(
                    "Workspace listing required multiple pages",
                    extra=operation_extra(operation_id, pages_fetched=pages_fetched, requested_limit=requested_limit),
                )

            result = [
                {
                    "operation_id": operation_id,
                    "id": str(ws.id),
                    "name": ws.display_name,
                    "description": ws.description,
                    "user_role": ws.user_role.name if ws.user_role else None,
                    "created_at": ws.created_at.isoformat() if ws.created_at else None,
                    "updated_at": ws.updated_at.isoformat() if ws.updated_at else None,
                }
                for ws in workspace_items
            ]

            await log_operation_event(
                ctx,
                logger,
                "Workspace listing complete",
                operation_id,
                returned_count=len(result),
                pages_fetched=pages_fetched,
            )

            return result
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to list workspaces",
                operation_id,
                e,
                filter_name=name or None,
                deleted=deleted,
                limit=limit,
            )
            raise

    @mcp.tool()
    async def get_workspace(
        workspace_id: str = "",
        workspace_name: str = "",
        ctx: Context | None = None,
    ) -> dict:
        """Get workspace details by ID or name.
        
        Args:
            workspace_id: Workspace UUID (provide either this or workspace_name)
            workspace_name: Workspace name (provide either this or workspace_id)
        """
        operation_id = str(uuid4())
        await log_operation_event(
            ctx,
            logger,
            "Getting workspace details",
            operation_id,
            workspace_id=workspace_id or None,
            workspace_name=workspace_name or None,
        )
        try:
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

            result = {
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

            await log_operation_event(
                ctx,
                logger,
                "Workspace details fetched",
                operation_id,
                workspace_id=result["id"],
            )

            return result_with_operation_id(operation_id, result)
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to get workspace details",
                operation_id,
                e,
                workspace_id=workspace_id or None,
                workspace_name=workspace_name or None,
            )
            raise
    
    @mcp.tool()
    async def list_objects(
        workspace_id: str,
        schema_id: str = "",
        deleted: bool = False,
        limit: int = 100,
        ctx: Context | None = None,
    ) -> list[dict]:
        """List objects in a workspace with optional filtering.
        
        Args:
            workspace_id: Workspace UUID
            schema_id: Filter by schema/object type (leave empty for no filter)
            deleted: Include deleted objects
            limit: Maximum number of results
        """
        operation_id = str(uuid4())

        if ctx:
            await ctx.info(
                "Listing objects",
                extra=operation_extra(
                    operation_id,
                    workspace_id=workspace_id,
                    schema_id=schema_id or None,
                    deleted=deleted,
                    limit=limit,
                ),
            )
        
        try:
            if ctx:
                await ctx.debug("Initializing Evo context")
            await ensure_initialized()
            if ctx:
                await ctx.debug("Evo context initialized")
            
            if ctx:
                await ctx.debug("Getting object client", extra=operation_extra(operation_id, workspace_id=workspace_id))
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            
            service_health = await object_client.get_service_health()
            service_health.raise_for_status()
            if ctx:
                await ctx.debug("Object client health check passed")
            
            if ctx:
                await ctx.debug("Fetching objects from service")
            objects = await object_client.list_objects(
                schema_id=None,
                deleted=deleted,
                limit=limit
            )

            if ctx:
                await ctx.debug(
                    "Received objects from service",
                    extra=operation_extra(operation_id, count=len(objects.items())),
                )
            
            result = [
                {
                    "operation_id": operation_id,
                    "id": str(obj.id),
                    "name": obj.name,
                    "path": obj.path,
                    "schema_id": obj.schema_id.sub_classification,
                    "version_id": obj.version_id,
                    "created_at": obj.created_at,
                    "created_by": obj.created_by,
                    "modified_at": obj.modified_at,
                    "modified_by": obj.modified_by,
                    "stage": obj.stage
                }
                for obj in objects.items()
            ]
            if ctx:
                await ctx.info(
                    "Object listing completed",
                    extra=operation_extra(operation_id, returned_count=len(result)),
                )
            return result
            
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to list objects",
                operation_id,
                e,
                workspace_id=workspace_id,
                schema_id=schema_id or None,
                deleted=deleted,
                limit=limit,
            )
            raise

    @mcp.tool()
    async def get_object(
        workspace_id: str,
        object_id: str = "",
        object_path: str = "",
        version: str = "",
        ctx: Context | None = None,
    ) -> dict:
        """Get object metadata by ID or path.
        
        Args:
            workspace_id: Workspace UUID
            object_id: Object UUID (provide either this or object_path)
            object_path: Object path (provide either this or object_id)
            version: Specific version ID (optional)
        """
        operation_id = str(uuid4())
        await log_operation_event(
            ctx,
            logger,
            "Getting object metadata",
            operation_id,
            workspace_id=workspace_id,
            object_id=object_id or None,
            object_path=object_path or None,
            version=version or None,
        )
        try:
            await ensure_initialized()
            object_client = await evo_context.get_object_client(UUID(workspace_id))

            if object_id:
                obj = await object_client.download_object_by_id(UUID(object_id), version=version)
            elif object_path:
                obj = await object_client.download_object_by_path(object_path, version=version)
            else:
                raise ValueError("Either object_id or object_path must be provided")

            result = {
                "id": str(obj.metadata.id),
                "name": obj.metadata.name,
                "path": obj.metadata.path,
                "schema_id": obj.metadata.schema_id.sub_classification,
                "version_id": obj.metadata.version_id,
                "created_at": obj.metadata.created_at,
                "created_by": obj.metadata.created_by,
                "modified_at": obj.metadata.modified_at,
                "modified_by": obj.metadata.modified_by,
                "stage": obj.metadata.stage,
            }

            await log_operation_event(
                ctx,
                logger,
                "Object metadata fetched",
                operation_id,
                object_id=result["id"],
                workspace_id=workspace_id,
            )

            return result_with_operation_id(operation_id, result)
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to get object metadata",
                operation_id,
                e,
                workspace_id=workspace_id,
                object_id=object_id or None,
                object_path=object_path or None,
                version=version or None,
            )
            raise


    @mcp.tool()
    async def list_my_instances(
        ctx: Context | None = None,
    ) -> list[dict]:
        """List instances the user has access to."""
        operation_id = str(uuid4())
        await log_operation_event(ctx, logger, "Listing available Evo instances", operation_id)
        try:
            await ensure_initialized()

            if ctx and evo_context.org_id:
                await ctx.info(
                    "Current Evo instance selected",
                    extra=operation_extra(operation_id, instance_id=str(evo_context.org_id)),
                )
            instances = await evo_context.discovery_client.list_organizations()
            result = [
                {
                    "operation_id": operation_id,
                    "id": str(instance.id),
                    "name": instance.display_name,
                    "hub_urls": [hub.url for hub in instance.hubs],
                }
                for instance in instances
            ]
            await log_operation_event(
                ctx,
                logger,
                "Available Evo instances listed",
                operation_id,
                returned_count=len(result),
            )
            return result
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to list available Evo instances",
                operation_id,
                e,
            )
            raise

    @mcp.tool()
    async def select_instance(
        instance_name: str | None = None,
        instance_id: UUID | None = None,
        ctx: Context | None = None,
    ) -> dict | None:
        """Select an instance to connect to.

        Subsequent tool invocations like "list workspaces" will act on this
        Evo Instance.

        The provided argument must match an instance returned by list_my_instances.

        Args:
            instance_id: Instance UUID (provide either this or instance_name)
            instance_name: Instance name (provide either this or instance_id)
        """
        operation_id = str(uuid4())
        await log_operation_event(
            ctx,
            logger,
            "Selecting Evo instance",
            operation_id,
            instance_name=instance_name,
            instance_id=str(instance_id) if instance_id else None,
        )
        try:
            await ensure_initialized()

            instances = await evo_context.discovery_client.list_organizations()
            for instance in instances:
                if instance.id == instance_id or instance.display_name == instance_name:
                    await evo_context.switch_instance(instance.id, instance.hubs[0].url)
                    await log_operation_event(
                        ctx,
                        logger,
                        "Selected Evo instance",
                        operation_id,
                        instance_id=str(instance.id),
                        instance_name=instance.display_name,
                    )
                    return result_with_operation_id(operation_id, {
                        "id": str(instance.id),
                        "name": instance.display_name,
                        "hub_urls": [hub.url for hub in instance.hubs],
                    })

            raise ValueError(
                f"No instance found for parameters {instance_id=} {instance_name=}. "
                "Check that the arguments match an instance returned by `list_my_instances`."
            )
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to select Evo instance",
                operation_id,
                e,
                instance_name=instance_name,
                instance_id=str(instance_id) if instance_id else None,
            )
            raise
