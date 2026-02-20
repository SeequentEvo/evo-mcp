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

        Only an instance admin or owner can add users to the instance. If a Forbidden error is returned from add_users_to_instance(), 
        inform the user of the tool that they do not have the required permissions to add users to the instance.
        If a user is already in the instance, an error will be returned - give the error details to the user of the tool
        and ask user if they wish to update the role of this user. If role update is requested, use `update_user_role_in_instance` tool instead.
        This will help in cases where the user is already in the instance but with a different role, 
        and we want to update the role of the user instead of adding the user again.
        With one request, assign the same role to multiple users by accepting a list of user emails and a list of role IDs.
        
        Args:
            user_emails: List of user email addresses to add. Accept single or multiple emails and make them to a list.
            Expected to be provided by the user of the tool. Prompt the user to provide email address/addresses if not provided.

                     
            role_ids: List of role IDs to assign to the users. Must match roles returned by `list_roles_in_instance`. 
            Following are the instructions regarding role_ids:
            Ask user of the tool to specify which roles to assign to the user/users. The default role is a read only "Evo user" role.
            Use `list_roles_in_instance` tool to list available roles in the instance and their corresponding role IDs. 
            The user can specify one or more role IDs to assign to the user/users.
            Do not call add_users_to_instance() without providing email and role_ids, as they are required parameters.
            
            
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
        user_id: UUID 
    ) -> dict|str:
        """Remove a user from the instance. This will revoke the user's access to the instance.
        Only an instance admin or owner can remove users from the instance. If a Forbidden error is returned from remove_instance_user(), 
        inform the user of the tool that they do not have the required permissions to remove users from the instance. 
        
        Args:
            user_email: The email address of the user to remove from the instance.
            Do not assume the email address from first name or other information, it should be provided by the user of the tool.
            Prompt the user to provide the email address if not provided. 

            user_id: The user ID of the user to remove from the instance. Following are the instructions to get the user_id:
            1. Use the tool `get_users_in_instance` to get all users in the instance
            2. Find the user_id for the given user email. 
            Pass the user_id to this tool to remove the user from the instance.
            If the user email does not exist in the instance, return a message saying the user is not in the instance.
        
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
        user_id: UUID,
        role_ids: list[UUID],
    ) -> dict|str:
        """Update the role of a user in the instance. This will change the user's access level in the instance.
        Only an instance admin or owner can update user roles in the instance. If a Forbidden error is returned from update_instance_user_roles(), 
        inform the user of the tool that they do not have the required permissions to update user roles in the instance. 
        If the user does not have the required role, they should not be able to update user roles in the instance.


        Args:
            user_email: The email address of the user to update role for in the instance.
            Do not assume the email address from first name or other information, it should be provided by the user of the tool.
            Prompt the user to provide the email address if not provided. 

            user_id: The user ID of the user to update role for in the instance. Following are the instructions to get the user_id:
            1. Use the tool `get_users_in_instance` to get all users in the instance
            2. Find the user_id for the given user email. 
            Pass the user_id to this tool to update the user's role in the instance.
            If the user email does not exist in the instance, return a message saying the user is not in the instance.

            role_ids: List of role IDs to assign to the user. Following are the instructions regarding role_ids:
            1. Must match roles returned by `list_roles_in_instance`. 
            2. Prompt the user to specify which roles to assign. The default role is a read only "Evo user" role.
            3. Do not call update_instance_user_roles() without providing user_id and role_ids, as they are required parameters.

        Returns:
            A dict with the email of the user whose role was updated and their new roles.
            
        """
        workspace_client = await get_workspace_client()

        await workspace_client.update_instance_user_roles(user_id=user_id, roles=role_ids)

        return {
            "user_role_updated": user_email,
            "new_roles": role_ids,
        }

  
