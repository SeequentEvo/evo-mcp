import functools
from uuid import UUID
from typing import Callable

from evo.workspaces.endpoints import InstanceUsersApi
from evo.workspaces.endpoints.models import AddInstanceUsersRequest, UserRoleMapping

from evo_mcp.context import evo_context, ensure_initialized


def register_instance_users_admin_tools(mcp):
    """Register tools for managing instance users with the FastMCP server."""

    async def get_workspace_client():
        await ensure_initialized()
        if workspace_client := evo_context.workspace_client:
            return workspace_client
        else:
            raise ValueError("Please ensure you are connected to an instance.")
  
    @mcp.tool()
    async def get_users_in_instance(
        count: int | None = 10000,
    ) -> list[dict]:
        """Get all users in the currently selected instance.
       
        This tool will allow an admin to see:
            * who has access to the instance,
            * who does not have access to the instance,
            * what roles a user has in the instance.

        The admin can take action to add or remove users from the instance based on this information.

        Use the `count` parameter to return only a sample of the users in the
        instance.

        Returns:
            A list of users in the instance, their names, email addresses and roles.
        """
        workspace_client = await get_workspace_client()

        async def read_pages_from_api(func: Callable, up_to: int | None = None, limit: int = 100):
            """Page through the API client method `func` until we get up_to results or run out of pages.

            `up_to` should be None to read all the pages.

            Only supports raw API clients, not SDK clients that return a evo.common.Pages object.
            """
            offset = 0
            ret = []
            while True:
                page = await func(offset=offset, limit=limit)
                ret.extend(page.items())

                if len(page) < limit:
                    break

                if up_to and len(ret) >= up_to:
                    ret = ret[:up_to]
                    break

                offset += limit

            return ret

        instance_users = await read_pages_from_api(
            functools.partial(
                workspace_client.list_instance_users
            ),
            up_to=count,
        )
        
        return [
            {
                "user_id": user.user_id,
                "email": user.email,
                "name": user.full_name,
                "roles": [role.name for role in user.roles]
            }
            for user in instance_users
        ]
    
    @mcp.tool()
    async def list_roles_in_instance(
    ) -> list[dict]:
        """List the roles available in the instance."""
        workspace_client = await get_workspace_client()

        instance_roles_response = await workspace_client.list_instance_roles()
        return instance_roles_response

    @mcp.tool()
    async def add_users_to_instance(
        user_emails: list[str],
        role_ids: list[UUID],
    ) -> dict|str:
        """Add one or more users to the selected instance.
        If the user is external, an invitation will be sent.

        Only an instance admin or owner can add users to the instance. If a Forbidden error is returned from add_users_to_instance(), 
        inform the user of the tool that they do not have the required permissions to add users to the instance.
        If a user is already in the instance, an error will be returned - give the error details to the user of the tool
        and ask the user if they wish to update the role of this user. If role update is requested, use `update_user_role_in_instance` tool instead.
        This will help in cases where the user is already in the instance but with a different role, 
        and we want to update the role of the user instead of adding the user again.
        With one request, assign the same role to multiple users by accepting a list of user emails and a list of role IDs.

        Args:
            user_emails: List of user email addresses to add.
            role_ids: List of role IDs to assign to the users. Must match
                roles returned by `list_roles_in_instance`. If the user doesn't
                specify a role, user the "Evo User" role for the selected
                instance.

        Returns:
            A dict with invitations sent and members added.
            Invitations are for external users who would need to accept the invitation to join the instance.
            Members are for users who are already part of the organization.
        """
        workspace_client = await get_workspace_client()
        
        users = {email : role_ids for email in user_emails}

        response = await workspace_client.add_users_to_instance(users=users)

        invitations = response.invitations or []
        members = response.members or []
        return {
            "invitations_sent": [invitation.email for invitation in invitations],
            "members_added": [member.email for member in members],
        }

    @mcp.tool()
    async def remove_user_from_instance(
        user_email: str,
        user_id: UUID 
    ) -> dict|str:
        """Remove a user from the selected instance. This will revoke the user's access to the instance.
        Only an instance admin or owner can remove users from the instance. If a Forbidden error is returned from remove_instance_user(), 
        inform the user of the tool that they do not have the required permissions to remove users from the instance. 
        Args:
            user_email: The email address of the user to remove from the instance.
            Do not assume the email address from first name or other information, it should be provided by the user of the tool.
            Prompt the user to provide the email address if not provided. 

            user_id: The user ID of the user to remove from the instance. Must
                match an entry returned from the `get_users_in_instance` tool.
        """
        workspace_client = await get_workspace_client()

        await workspace_client.remove_instance_user(user_id=user_id)

        return {
            "user_removed": user_email,
        }

    @mcp.tool()
    async def update_user_role_in_instance(
        user_email: str,
        user_id: UUID,
        role_ids: list[UUID],
    ) -> dict|str:
        """Update the role of a user in the instance. This will change the user's access level in the instance.
        Only an instance admin or owner can update user roles in the instance. If a Forbidden error is returned from update_instance_user_roles(), 
        inform the user of the tool that they do not have the required permissions to update user roles in the instance.

        Args:
            user_email: The email address of the user to update the role of.
            Do not assume the email address from first name or other information, it should be provided by the user of the tool.
            Prompt the user to provide the email address if not provided. 

            user_id: The user ID of the user to update the role of. Must match
                an entry returned by the `get_users_in_instance` tool.

            role_ids: List of role IDs to assign to the user. Role IDs must
                mach an entry returned by the `list_roles_in_instance` tool.
                The default role is the "Evo user" role for the selected
                instance.
        """
        workspace_client = await get_workspace_client()

        await workspace_client.update_instance_user_roles(user_id=user_id, roles=role_ids)

        return {
            "user_role_updated": user_email,
            "new_roles": role_ids,
        }

  
