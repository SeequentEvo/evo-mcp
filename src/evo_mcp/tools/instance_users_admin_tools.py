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
        """Get all user members in an instance the user is connected to, at a time.
       
        This tool will allow an admin to see who has access to the instance.
        This tool will also allow admin to see which user does not have access to the instance.
        Then admin can take action to add or remove users from the instance based on this information.

        Returns:
            A list of users in the instance
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

                if len(page) == 0 or len(page) < limit:
                    break

                if up_to and len(ret) >= up_to:
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
        """List the roles available in the instance. """
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
        
        
        Args:
            user_emails: List of user email addresses to add. Accept single or multiple emails and make them to a list.
            Do not assume the email address from first name or other information, it should be provided by the user of the tool.
            Use `get_users_in_instance` tool to see if the current user in the instance has the admin or owner role, 
            if not, they should not be able to add users to the instance.
            Use `get_users_in_instance` tool to see which users are already in the instance and which users are not in the instance.
            If a user is already in the instance, they will be skipped and not added again; ask user if they wish to update the role of this user
            with `update_user_role_in_instance` tool instead.
            This will help in cases where the user is already in the instance but with a different role, 
            and we want to update the role of the user instead of adding the user again.
            
            role_ids: List of role IDs to assign to the users. Must match roles returned by `list_roles_in_instance`. 
            Prompt the user to specify which roles to assign.
            The default role is a read only "Evo user" role.
            
        Returns:
            A dict with invitations sent and members added.
            Invitations are for external users who would need to accept the invitation to join the instance.
            Members are for users who are already part of the organization.
            
            String error message if there was an error adding users.
            
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
        user_id: UUID | None = None,
    ) -> dict|str:
        """Remove a user from the instance. This will revoke the user's access to the instance.
        Check if the user requesting the removal has the admin or owner role to remove users from the instance
        by calling `get_users_in_instance` tool. 
        If the user does not have the required role, they should not be able to remove users from the instance.
        
        Args:
            user_email: The email address of the user to remove from the instance.
            Do not assume the email address from first name or other information, it should be provided by the user of the tool.
            From the user list obtained from `get_users_in_instance`, for the given user email, you can find the corresponding user_id. 
            Pass the user_id to this tool to remove the user from the instance.
            If the user email does not exist in the instance, return a message saying the user is not in the instance.

            Use `get_users_in_instance` tool to see which users are in the instance and their email addresses.
        
        Returns:
            A dict with the email of the user removed.
            
        """
        workspace_client = await get_workspace_client()

        await workspace_client.remove_instance_user(user_id=user_id)

        return {
            "user_removed": user_email,
        }

    @mcp.tool()
    async def update_user_role_in_instance(
        user_email: str,
        user_id: UUID | None = None,
        new_role_ids: list[UUID] | None = [],
    ) -> dict|str:
        """Update the role of a user in the instance. This will change the user's access level in the instance.
        Check if the user requesting the role update has the admin or owner role to update user roles in the instance
        by calling `get_users_in_instance` tool. 
        If the user does not have the required role, they should not be able to update user roles in the instance.

        Args:
            user_email: The email address of the user to update role for in the instance.
            Do not assume the email address from first name or other information, it should be provided by the user of the tool.
            From the user list obtained from `get_users_in_instance`, for the given user email, you can find the corresponding user_id. 
            Pass the user_id to this tool to update the user's role in the instance.
            If the user email does not exist in the instance, return a message saying the user is not in the instance.

            new_role_ids: List of new role IDs to assign to the user. Must match roles returned by `list_roles_in_instance`. 
            Prompt the user to specify which new roles to assign.
            The default role is a read only "Evo user" role.

        Returns:
            A dict with the email of the user whose role was updated and their new roles.
            
        """
        workspace_client = await get_workspace_client()

        await workspace_client.update_instance_user_roles(user_id=user_id, roles=new_role_ids)

        return {
            "user_role_updated": user_email,
            "new_roles": new_role_ids,
        }

  
