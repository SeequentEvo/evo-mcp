# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for workspace administration tasks that require org-admin privileges.

These tools use the Evo Workspaces Admin API endpoints, which allow organization
admin users to access any workspace regardless of their role within it.
"""

import logging
from uuid import UUID

from evo.workspaces.endpoints.api import AdminApi
from evo.workspaces.endpoints.models import (
    AssignRoleRequest,
    BulkUserRoleAssignmentsRequest,
    RoleEnum,
    UserRoleAssignmentRequest,
    UserRoleViaEmail,
)
from evo.workspaces.endpoints.models import (
    UserRole as UserRoleModel,
)

from evo_mcp.context import ensure_initialized, evo_context

logger = logging.getLogger(__name__)


def register_workspace_admin_tools(mcp):
    """Register workspace admin tools with the FastMCP server."""

    def _get_admin_api() -> AdminApi:
        """Get the AdminApi client from the workspace client."""
        if evo_context.workspace_client is None:
            raise ValueError("Please ensure you are connected to an instance.")
        return evo_context.workspace_client._admin_api

    @mcp.tool()
    async def get_my_instance_role() -> dict:
        """Get the current user's role on the selected Evo instance.

        This tells the user whether they are an admin, owner, or regular user
        of the instance. Admin/owner users can perform workspace admin operations
        that regular users cannot.

        Returns:
            A dict with the user's ID, name, email, and their instance roles.
            If the user has an admin role, the response will indicate that admin
            workspace tools are available to them.
        """
        await ensure_initialized()

        if evo_context.workspace_client is None:
            raise ValueError("Please ensure you are connected to an instance.")

        # Get the current user's ID from the cached access token
        import jwt

        access_token = evo_context.get_access_token_from_cache()
        if not access_token:
            raise ValueError("No valid access token available. Please re-authenticate.")

        claims = jwt.decode(access_token, options={"verify_signature": False, "verify_exp": False})
        current_user_id = claims.get("sub") or claims.get("oid")
        if not current_user_id:
            raise ValueError("Could not determine user ID from access token.")

        # Look up the user in instance users to get their roles
        workspace_client = evo_context.workspace_client
        page = await workspace_client.list_instance_users(limit=100, offset=0)
        current_user = None
        for user in page.items():
            if str(user.user_id) == str(current_user_id):
                current_user = user
                break

        if current_user is None:
            return {
                "user_id": current_user_id,
                "instance_roles": [],
                "is_admin": False,
                "message": "Could not find your user in the instance user list.",
            }

        role_names = [role.name for role in current_user.roles]
        is_admin = any("admin" in name.lower() or "owner" in name.lower() for name in role_names)

        result = {
            "user_id": str(current_user.user_id),
            "email": getattr(current_user, "email", None),
            "name": getattr(current_user, "full_name", None),
            "instance_roles": role_names,
            "is_admin": is_admin,
        }

        if is_admin:
            result["admin_capabilities"] = (
                "As an instance admin, you can use admin workspace tools to: "
                "list ALL workspaces (including ones you don't have a role in), "
                "get any workspace by ID, "
                "list users and their roles in any workspace, "
                "assign or remove user roles in any workspace, "
                "bulk assign roles across multiple workspaces, "
                "and get organization settings."
            )
        else:
            result["message"] = (
                "You are a regular user. You can only manage workspaces where "
                "you have been assigned a role (owner/editor/viewer)."
            )

        return result

    @mcp.tool()
    async def admin_list_workspace_users(workspace_id: str) -> dict:
        """List all users and their roles within any workspace using admin privileges.

        This allows an admin to see who has access to any workspace in the instance,
        even workspaces where the admin themselves has no direct role.

        Only organization admins can use this tool.

        Args:
            workspace_id: The workspace UUID to list users for
        """
        await ensure_initialized()
        admin_api = _get_admin_api()
        org_id = str(evo_context.org_id)

        response = await admin_api.list_user_roles_admin(
            workspace_id=workspace_id,
            org_id=org_id,
        )

        users = []
        for user in response.results:
            users.append(
                {
                    "user_id": str(user.user_id),
                    "email": getattr(user, "email", None),
                    "full_name": getattr(user, "full_name", None),
                    "role": str(user.role) if hasattr(user, "role") else None,
                }
            )

        return {
            "workspace_id": workspace_id,
            "users": users,
            "total_users": len(users),
        }

    @mcp.tool()
    async def admin_assign_workspace_role(
        workspace_id: str,
        user_id: str = "",
        user_email: str = "",
        role: str = "viewer",
    ) -> dict:
        """Assign a user a role in any workspace using admin privileges.

        This allows an admin to grant access to workspaces they don't own.
        Provide either user_id or user_email to identify the user.

        Only organization admins can use this tool.

        Args:
            workspace_id: The workspace UUID to assign the role in
            user_id: The user's UUID (provide either this or user_email)
            user_email: The user's email address (provide either this or user_id)
            role: The role to assign - must be "owner", "editor", or "viewer"
        """
        await ensure_initialized()
        admin_api = _get_admin_api()
        org_id = str(evo_context.org_id)

        valid_roles = {"owner", "editor", "viewer"}
        if role.lower() not in valid_roles:
            raise ValueError(f"Invalid role '{role}'. Must be one of: {', '.join(valid_roles)}")

        role_enum = RoleEnum(role.lower())

        if user_id:
            assign_request = AssignRoleRequest(root=UserRoleModel(user_id=UUID(user_id), role=role_enum))
        elif user_email:
            assign_request = AssignRoleRequest(root=UserRoleViaEmail(email=user_email, role=role_enum))
        else:
            raise ValueError("Either user_id or user_email must be provided.")

        response = await admin_api.assign_user_role_admin(
            org_id=org_id,
            workspace_id=workspace_id,
            assign_role_request=assign_request,
        )

        return {
            "success": True,
            "workspace_id": workspace_id,
            "user_id": str(response.user_id) if hasattr(response, "user_id") else user_id or user_email,
            "role": str(response.role) if hasattr(response, "role") else role,
        }

    @mcp.tool()
    async def admin_remove_workspace_user(
        workspace_id: str,
        user_id: str,
    ) -> dict:
        """Remove a user's role from any workspace using admin privileges.

        This revokes the user's access to the specified workspace.

        Only organization admins can use this tool.

        Args:
            workspace_id: The workspace UUID to remove the user from
            user_id: The UUID of the user to remove
        """
        await ensure_initialized()
        admin_api = _get_admin_api()
        org_id = str(evo_context.org_id)

        await admin_api.delete_user_role_admin(
            workspace_id=workspace_id,
            user_id=user_id,
            org_id=org_id,
        )

        return {
            "success": True,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "message": "User role removed from workspace.",
        }

    @mcp.tool()
    async def admin_bulk_assign_roles(
        assignments: list[dict],
    ) -> dict:
        """Assign roles to multiple users across multiple workspaces in a single request.

        This is efficient for setting up access for many users at once.
        Maximum 100 assignments per request.

        Only organization admins can use this tool.

        Args:
            assignments: A list of role assignment dicts, each containing:
                - user_id: The user's UUID
                - workspace_id: The workspace UUID
                - role: The role to assign ("owner", "editor", or "viewer")
        """
        await ensure_initialized()
        admin_api = _get_admin_api()
        org_id = str(evo_context.org_id)

        if len(assignments) > 100:
            raise ValueError("Maximum 100 role assignments per request.")

        valid_roles = {"owner", "editor", "viewer"}
        role_assignments = []
        for assignment in assignments:
            role_str = assignment.get("role", "").lower()
            if role_str not in valid_roles:
                raise ValueError(f"Invalid role '{role_str}' in assignment. Must be one of: {', '.join(valid_roles)}")
            role_assignments.append(
                UserRoleAssignmentRequest(
                    user_id=UUID(assignment["user_id"]),
                    workspace_id=UUID(assignment["workspace_id"]),
                    role=RoleEnum(role_str),
                )
            )

        request = BulkUserRoleAssignmentsRequest(role_assignments=role_assignments)

        await admin_api.bulk_assign_roles_admin(
            org_id=org_id,
            bulk_user_role_assignments_request=request,
        )

        return {
            "success": True,
            "assignments_processed": len(role_assignments),
        }

    @mcp.tool()
    async def admin_list_user_workspaces(user_id: str, limit: int = 50, offset: int = 0) -> dict:
        """List all workspaces that a specific user has a role in.

        This allows an admin to see which workspaces a particular user has access to.

        Only organization admins can use this tool.

        Args:
            user_id: The UUID of the user to look up
            limit: Maximum number of results (max 100)
            offset: Pagination offset
        """
        await ensure_initialized()
        admin_api = _get_admin_api()
        org_id = str(evo_context.org_id)

        response = await admin_api.list_user_workspaces_admin(
            org_id=org_id,
            user_id=user_id,
            limit=min(limit, 100),
            offset=offset,
        )

        workspaces = []
        for ws in response.results:
            workspaces.append(
                {
                    "workspace_id": str(ws.id) if hasattr(ws, "id") else None,
                    "workspace_name": getattr(ws, "name", None),
                    "user_role": getattr(ws, "user_role", None),
                    "created_at": str(ws.created_at) if getattr(ws, "created_at", None) else None,
                    "updated_at": str(ws.updated_at) if getattr(ws, "updated_at", None) else None,
                }
            )

        return {
            "user_id": user_id,
            "total": getattr(response.links, "total", len(workspaces)),
            "offset": offset,
            "limit": limit,
            "workspaces": workspaces,
        }

    @mcp.tool()
    async def admin_get_organization_settings() -> dict:
        """Get the organization settings for the current instance.

        Returns settings like ML enablement status at the organization level.

        Only organization admins can use this tool.
        """
        await ensure_initialized()
        admin_api = _get_admin_api()
        org_id = str(evo_context.org_id)

        response = await admin_api.get_organization_settings(org_id=org_id)

        return {
            "id": str(response.id) if hasattr(response, "id") else None,
            "settings": {
                "ml_enabled": response.settings.ml_enabled
                if hasattr(response, "settings") and hasattr(response.settings, "ml_enabled")
                else None,
            },
            "created_at": str(response.created_at) if getattr(response, "created_at", None) else None,
            "created_by": str(response.created_by) if getattr(response, "created_by", None) else None,
            "updated_at": str(response.updated_at) if getattr(response, "updated_at", None) else None,
            "updated_by": str(response.updated_by) if getattr(response, "updated_by", None) else None,
        }
