import functools
from typing import Callable

from evo.workspaces.endpoints import InstanceUsersApi
from evo.workspaces.endpoints.models import AddInstanceUsersRequest, UserRoleMapping

from evo_mcp.context import evo_context, ensure_initialized

def register_instance_user_admin_tools(mcp):
    """Register tools for managing instance users with the FastMCP server."""
  
    @mcp.tool()
    async def get_users_in_instance(
        count: int | None = 10,
    ) -> list[dict]:
        """Get all users of an instance the user is connected to.
        
        This would allow an admin to see who has access to the instance.
        This would also allow admin to see which user does not have access to the instance.
        Then admin can take action to add or remove users from the instance based on this information.

        If a specific instance is not selected, it uses the currently selected instance.
        If no instance is selected, it asks the user to select one first.
        
        Returns:
            A list of users in the instance
            
        Raises:
            ValueError: If no instance is selected.
        """
        await ensure_initialized()
        
        if not evo_context.org_id:
            raise ValueError("No instance selected. Please select an instance first.")
        
        #TODO maybe move this to context.py maybe or all instance related code to a separate instance tools file
        # Also I could not find a client for the instance users in the SDK, so I used the endpoint directly
        instance_users_api_client = InstanceUsersApi(evo_context.connector)

        async def read_pages_from_api(func: Callable, up_to: int | None = None, limit: int = 100):
            """Page through the API client method `func` until we get up_to results or run out of pages.

            `up_to` should be None to read all the pages.

            Only supports raw API clients, not SDK clients that return a evo.common.Pages object.
            """
            offset = 0
            ret = []
            while True:
                response = await func(offset=offset, limit=limit)
                # We could probably look at the type of `response` and handle
                # `Page` objects here too.
                ret.extend(response.results)

                if up_to and len(ret) >= up_to:
                    break
                elif len(response.results) < limit or len(ret) >= up_to:
                    break

                offset += limit

            return ret
        
        instance_users = await read_pages_from_api(
            functools.partial(
                instance_users_api_client.list_instance_users,
                org_id=evo_context.org_id,
            ),
            up_to=count,
            limit=min([count, 100]) if count else None,
        )
        
        return [
            {
                "id": str(user.id),
                # "email": user.email,
                "name": user.full_name,
                "roles": [role.name for role in user.roles]
            }
            for user in instance_users
        ]
        
    @mcp.tool()
    async def add_users_to_instance(
        user_emails: list[str],
    ) -> dict|str:
        """Add one or more users to the selected instance with read only role.
        If the user is external, an invitation will be sent.
        
        
        Args:
            user_emails: List of user email addresses to add. Accept single or multiple emails and make them to a list.
            
        Returns:
            A dict with invitations sent and members added.
            Invitations are for external users who would need to accept the invitation to join the instance.
            Members are for users who are already part of the organization.
            
            String error message if there was an error adding users.
            
        Raises:
            ValueError: If no instance is selected.
        """
        await ensure_initialized()
        
        if not evo_context.org_id:
            raise ValueError("No instance selected. Please select an instance first.")
        
        instance_users_api_client = InstanceUsersApi(evo_context.connector)
        
      #  TODO check if the user is the owner/admin of the instance before adding users.
        try:
            instance_roles_response = await instance_users_api_client.list_instance_user_roles(org_id=evo_context.org_id)
            instance_roles = instance_roles_response.roles
            
            #TODO make role configurable in the future. Right now we are assigning "Evo User" role by default.
            evo_user_role = next((role for role in instance_roles if role.name == "Evo User"), None)
            
            response = await instance_users_api_client.add_instance_users(
                org_id=evo_context.org_id,
                add_instance_users_request=AddInstanceUsersRequest(
                    users = [UserRoleMapping(email=email, roles=[evo_user_role.id]) 
                             for email in user_emails]
                    )
            )

        except Exception as e:
            ## To see debug logs on local set the log_level to DEBUG when creating FastMCP instance in mcp_tools.py
            ## Eg: mcp = FastMCP("EVO SDK MCP Server", log_level="DEBUG")
            # sys.exc_info()
            return "Error adding users: " + str(e)
        
        invitations = response.invitations or []
        members = response.members or []
        return {
            "invitations_sent": [invitation.email for invitation in invitations],
            "members_added": [member.email for member in members],
        }

  
