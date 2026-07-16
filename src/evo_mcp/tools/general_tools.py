# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for general operations (health checks, object CRUD, etc).
"""

import asyncio
import hashlib
import hmac
import logging
import os
import time
from uuid import UUID

from evo.objects.typed import object_from_uuid
from evo.widgets import get_portal_url, get_viewer_url
from fastmcp import Context

from evo_mcp.context import get_evo_context
from evo_mcp.runtime_paths import get_debug_log_path
from evo_mcp.utils.tool_support import get_workspace_context, get_workspace_environment, schema_label

# Set up logging to file for debugging
_DEBUG_LOG_PATH = get_debug_log_path()
_DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    filename=str(_DEBUG_LOG_PATH),
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

_DELETE_TOKEN_TTL_SECONDS = 300  # 5 minutes
_DELETE_TOKEN_SECRET = os.environ.get("EVO_MCP_DELETE_SECRET")
if not _DELETE_TOKEN_SECRET:
    # In HTTP/multi-worker mode, tokens must be consistent across workers and restarts.
    # Require an explicit secret to avoid silent token validation failures.
    if os.environ.get("MCP_TRANSPORT", "stdio").lower() != "stdio":
        raise RuntimeError(
            "EVO_MCP_DELETE_SECRET must be set when running in HTTP transport mode. "
            "Deletion tokens will not work reliably across multiple workers or restarts without it."
        )
    _DELETE_TOKEN_SECRET = os.urandom(32).hex()
    logger.warning(
        "EVO_MCP_DELETE_SECRET is not set. Using a random per-process secret for deletion tokens. "
        "Tokens will not survive restarts or work across multiple workers/replicas. "
        "Set EVO_MCP_DELETE_SECRET to a stable secret in production."
    )


def _create_deletion_token(workspace_id: str) -> str:
    """Create an HMAC-signed deletion token embedding workspace ID and expiry."""
    expires_at = int(time.time()) + _DELETE_TOKEN_TTL_SECONDS
    payload = f"{workspace_id}:{expires_at}"
    signature = hmac.new(
        _DELETE_TOKEN_SECRET.encode() if isinstance(_DELETE_TOKEN_SECRET, str) else _DELETE_TOKEN_SECRET,
        payload.encode(),
        hashlib.sha256,
    ).hexdigest()
    return f"{payload}:{signature}"


def _verify_deletion_token(token: str, workspace_id: str) -> None:
    """Verify an HMAC-signed deletion token. Raises ValueError on failure."""
    parts = token.split(":")
    if len(parts) != 3:
        raise ValueError("Invalid confirmation token format.")

    token_ws_id, expires_at_str, provided_sig = parts

    if token_ws_id != workspace_id:
        raise ValueError(
            "Confirmation token does not match the requested workspace. "
            "Call delete_workspace with confirm=False first to get a new token."
        )

    expected_payload = f"{token_ws_id}:{expires_at_str}"
    expected_sig = hmac.new(
        _DELETE_TOKEN_SECRET.encode() if isinstance(_DELETE_TOKEN_SECRET, str) else _DELETE_TOKEN_SECRET,
        expected_payload.encode(),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(provided_sig, expected_sig):
        raise ValueError("Invalid confirmation token.")

    if int(expires_at_str) < int(time.time()):
        raise ValueError("Confirmation token has expired. Call delete_workspace with confirm=False to get a new token.")


def register_general_tools(mcp):
    """Register all general tools with the FastMCP server."""

    async def _resolve_workspace(workspace_id: str = "", workspace_name: str = "", *, deleted: bool = False):
        """Resolve a workspace from an ID or name.

        Args:
            workspace_id: Workspace UUID string.
            workspace_name: Workspace display name.
            deleted: If True, search among deleted workspaces.

        Returns:
            A tuple of (evo_context, workspace).

        Raises:
            ValueError: If neither argument is provided, both are provided,
                or the workspace is not found.
        """
        if workspace_id and workspace_name:
            raise ValueError("Provide either workspace_id or workspace_name, not both.")
        if not workspace_id and not workspace_name:
            raise ValueError("Either workspace_id or workspace_name must be provided")

        evo_context = await get_evo_context()
        if workspace_id:
            if deleted:
                # get_workspace() may not return soft-deleted workspaces,
                # so search by ID among deleted workspaces instead.
                # Use pagination to ensure we don't miss the target workspace.
                offset = 0
                page_size = 100
                while True:
                    workspaces = await evo_context.workspace_client.list_workspaces(
                        deleted=True, offset=offset, limit=page_size
                    )
                    matching = [ws for ws in workspaces.items() if str(ws.id) == workspace_id]
                    if matching:
                        return evo_context, matching[0]
                    if workspaces.is_last:
                        break
                    next_offset = workspaces.next_offset
                    if next_offset <= offset:
                        raise RuntimeError(
                            f"Pagination stalled while searching for deleted workspace '{workspace_id}': "
                            f"offset={offset}, next_offset={next_offset}. "
                            "This may indicate an issue with the workspace listing API."
                        )
                    offset = next_offset
                raise ValueError(f"Deleted workspace '{workspace_id}' not found")
            workspace = await evo_context.workspace_client.get_workspace(UUID(workspace_id))
            return evo_context, workspace
        # workspace_name path
        workspaces = await evo_context.workspace_client.list_workspaces(name=workspace_name, deleted=deleted)
        matching = [ws for ws in workspaces.items() if ws.display_name == workspace_name]
        if not matching:
            status = "Deleted workspace" if deleted else "Workspace"
            raise ValueError(f"{status} '{workspace_name}' not found")
        return evo_context, matching[0]

    @mcp.tool()
    async def workspace_health_check(workspace_id: str = "") -> dict:
        """Check health status of Evo services.

        Args:
            workspace_id: Workspace UUID to check object service (optional)
        """
        results = {}

        evo_context = await get_evo_context()
        if evo_context.workspace_client:
            workspace_health = await evo_context.workspace_client.get_service_health()
            results["workspace_service"] = {
                "service": workspace_health.service,
                "status": workspace_health.status,
            }

        if workspace_id:
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            object_health = await object_client.get_service_health()
            results["object_service"] = {
                "service": object_health.service,
                "status": object_health.status,
            }

        return results

    @mcp.tool()
    async def list_workspaces(name: str = "", deleted: bool = False, limit: int = 50) -> list[dict]:
        """List workspaces with optional filtering by name or deleted status.

        Args:
            name: Filter by workspace name (leave empty for no filter)
            deleted: Include deleted workspaces
            limit: Maximum number of results
        """
        evo_context = await get_evo_context()

        workspaces = await evo_context.workspace_client.list_workspaces(
            name=name if name else None, deleted=deleted, limit=limit
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
    async def get_workspace(workspace_id: str = "", workspace_name: str = "") -> dict:
        """Get workspace details by ID or name.

        Args:
            workspace_id: Workspace UUID (provide either this or workspace_name)
            workspace_name: Workspace name (provide either this or workspace_id)
        """
        evo_context, workspace = await _resolve_workspace(workspace_id, workspace_name)

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
    async def delete_workspace(
        workspace_id: str = "",
        workspace_name: str = "",
        confirm: bool = False,
        confirmation_token: str = "",
    ) -> dict:
        """Delete a workspace by ID or name. This is a destructive two-step operation.

        IMPORTANT: You MUST call this tool twice. Do NOT set confirm=True on the first call.

        Step 1: Call with confirm=False (the default) to preview the workspace
        details and receive a confirmation_token. Show the preview to the user
        and ask for explicit confirmation before proceeding.

        Step 2: Only after the user has explicitly confirmed, call again with
        confirm=True and the confirmation_token returned from Step 1.

        Never skip Step 1. Never set confirm=True without a valid confirmation_token
        obtained from a prior preview call. The token expires after 5 minutes.

        Args:
            workspace_id: Workspace UUID (provide either this or workspace_name)
            workspace_name: Workspace name (provide either this or workspace_id)
            confirm: MUST be False on the first call. Set to True only on the second
                call after the user has reviewed and explicitly confirmed deletion.
            confirmation_token: Token returned from the Step 1 preview call.
                Required when confirm=True. Do not fabricate this value.
        """
        evo_context, workspace = await _resolve_workspace(workspace_id, workspace_name)

        if workspace.user_role is None or workspace.user_role.name not in ("owner",):
            role_name = workspace.user_role.name if workspace.user_role else "unknown"
            raise PermissionError(
                f"You do not have permission to delete workspace '{workspace.display_name}'. "
                f"Your role is '{role_name}'. Only owners can delete workspaces."
            )

        ws_id_str = str(workspace.id)

        if not confirm:
            token = _create_deletion_token(ws_id_str)
            return {
                "id": ws_id_str,
                "name": workspace.display_name,
                "description": workspace.description,
                "user_role": workspace.user_role.name if workspace.user_role else None,
                "confirmation_token": token,
                "message": (
                    f"Are you sure you want to delete workspace '{workspace.display_name}' "
                    f"(ID: {workspace.id})? Call delete_workspace again with confirm=True "
                    f"and the returned confirmation_token to proceed. Token expires in 5 minutes."
                ),
            }

        if not confirmation_token:
            raise ValueError(
                "A confirmation_token is required when confirm=True. "
                "Call delete_workspace with confirm=False first to get a token."
            )

        _verify_deletion_token(confirmation_token, ws_id_str)

        await evo_context.workspace_client.delete_workspace(workspace.id)
        return {
            "id": ws_id_str,
            "name": workspace.display_name,
            "message": f"Workspace '{workspace.display_name}' deleted successfully",
        }

    @mcp.tool()
    async def restore_workspace(workspace_id: str = "", workspace_name: str = "") -> dict:
        """Restore a soft-deleted workspace by ID or name.

        Args:
            workspace_id: Workspace UUID (provide either this or workspace_name)
            workspace_name: Workspace name (provide either this or workspace_id)
        """
        evo_context, workspace = await _resolve_workspace(workspace_id, workspace_name, deleted=True)
        ws_id = workspace.id

        # TODO: Replace with a public SDK method when available.
        workspaces_api = getattr(evo_context.workspace_client, "_workspaces_api", None)
        if workspaces_api is None or not hasattr(workspaces_api, "restore_soft_deleted_workspace"):
            raise NotImplementedError(
                "Workspace restore is not supported by the current version of the Evo SDK. "
                "The internal API '_workspaces_api.restore_soft_deleted_workspace' is unavailable."
            )
        await workspaces_api.restore_soft_deleted_workspace(
            workspace_id=str(ws_id),
            org_id=str(evo_context.org_id),
            deleted="false",
        )
        workspace = await evo_context.workspace_client.get_workspace(ws_id)
        return {
            "id": str(ws_id),
            "name": workspace.display_name,
            "message": f"Workspace '{workspace.display_name}' (ID: {ws_id}) restored successfully",
        }

    @mcp.tool()
    async def list_objects(
        workspace_id: str, schema_id: str = "", deleted: bool = False, limit: int = 100
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
            evo_context = await get_evo_context()

            logger.debug(f"Getting object client for workspace {workspace_id}")
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            logger.debug(f"Got object_client: {object_client}")

            service_health = await object_client.get_service_health()
            service_health.raise_for_status()
            logger.debug("Object client health check passed")

            logger.debug("Calling list_objects()")
            objects = await object_client.list_objects(
                schema_id=None,  # [schema_id] if schema_id else None,
                deleted=deleted,
                limit=limit,
            )

            logger.debug(f"list_objects() returned {len(objects.items())} objects")

            result = [
                {
                    "id": str(obj.id),
                    "name": obj.name,
                    "path": obj.path,
                    "schema_id": obj.schema_id.sub_classification,
                    "version_id": obj.version_id,
                    "created_at": obj.created_at,
                    "created_by": obj.created_by,
                    "modified_at": obj.modified_at,
                    "modified_by": obj.modified_by,
                    "stage": obj.stage,
                }
                for obj in objects.items()
            ]
            logger.info(f"evo_list_objects completed successfully with {len(result)} objects")
            return result

        except Exception as e:
            logger.error(f"Error in evo_list_objects: {type(e).__name__}: {str(e)}", exc_info=True)
            raise

    @mcp.tool()
    async def get_object(workspace_id: str, object_id: str = "", object_path: str = "", version: str = "") -> dict:
        """Get object metadata by ID or path.

        Args:
            workspace_id: Workspace UUID
            object_id: Object UUID (provide either this or object_path)
            object_path: Object path (provide either this or object_id)
            version: Specific version ID (optional)
        """
        evo_context = await get_evo_context()
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
            "created_at": obj.metadata.created_at,
            "created_by": obj.metadata.created_by,
            "modified_at": obj.metadata.modified_at,
            "modified_by": obj.metadata.modified_by,
            "stage": obj.metadata.stage,
        }

    @mcp.tool()
    async def list_my_instances(
        ctx: Context,
    ) -> list[dict]:
        """List instances the user has access to."""
        evo_context = await get_evo_context()

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

        The provided argument must match an instance returned by list_my_instances.

        Args:
            instance_id: Instance UUID (provide either this or instance_name)
            instance_name: Instance name (provide either this or instance_id)
        """
        evo_context = await get_evo_context()

        instances = await evo_context.discovery_client.list_organizations()
        for instance in instances:
            if instance.id == instance_id or instance.display_name == instance_name:
                await evo_context.switch_instance(instance.id, instance.hubs[0].url)
                return instance

        raise ValueError(
            f"No instance found for parameters {instance_id=} {instance_name=}. "
            "Check that the arguments match an instance returned by `list_my_instances`."
        )

    @mcp.tool()
    async def viewer_generate_multi_object_links(
        workspace_id: str,
        object_ids: list[str],
    ) -> dict:
        """Generate portal and viewer links for an explicit user-supplied object list."""
        if len(object_ids) == 0:
            raise ValueError("object_ids must contain at least one object ID.")

        context = await get_workspace_context(workspace_id)
        environment = await get_workspace_environment(workspace_id)
        unique_requested_ids = list(dict.fromkeys(object_ids))
        try:
            resolved_objects = await asyncio.gather(
                *(object_from_uuid(context, object_id) for object_id in unique_requested_ids)
            )
        except Exception as exc:
            raise ValueError(f"Could not resolve one or more object IDs for viewer-link generation: {exc}") from exc

        unique_ids = list(dict.fromkeys(str(obj.metadata.id) for obj in resolved_objects))
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
