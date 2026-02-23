"""
Configuration and Context Management for Evo SDK.

This module handles connection initialization, OAuth authentication,
and client management for the Evo platform.
"""

import logging
import os
import json
import jwt
from pathlib import Path
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone

from dotenv import load_dotenv
from evo.aio import AioTransport
from evo.oauth import OAuthConnector, AuthorizationCodeAuthorizer, AccessTokenAuthorizer, EvoScopes
from evo.discovery import DiscoveryAPIClient
from evo.common import APIConnector

from evo.files import FileAPIClient
from evo.objects import ObjectAPIClient
from evo.workspaces import WorkspaceAPIClient


# Load environment variables from .env file
# Look for .env in the project root (parent of src directory)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Set up local logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if os.environ.get("DEBUG") == "1" else logging.INFO)

class EvoContext:
    """Maintains Evo SDK connection state and clients."""
    
    def __init__(self):
        self.transport: Optional[AioTransport] = None
        self.connector: Optional[APIConnector] = None
        self.workspace_client: Optional[WorkspaceAPIClient] = None
        self.discovery_client: Optional[DiscoveryAPIClient] = None
        self._initialized: bool = False
        self.org_id: Optional[UUID] = None
        self.hub_url: Optional[str] = None
        repo_root = Path(__file__).parent.parent.parent
        self.cache_path = repo_root / ".cache"
        if not self.cache_path.exists():
            self.cache_path.mkdir()

        self._cached_variables = [
            "org_id",
            "hub_url",
        ]


    def load_variables_from_cache(self):
        try:
            with open(self.cache_path / "variables.json", encoding="utf-8") as f:
                variables = json.load(f)
        except FileNotFoundError:
            return

        for var in self._cached_variables:
            if hasattr(self, var):
                if var == "org_id":
                    # TODO: put persistent variables in a pydantic model or
                    # something to avoid this special casing here and in
                    # save_....
                    variables[var] = UUID(variables[var])
                setattr(self, var, variables[var])


    def save_variables_to_cache(self):
        variables = {}

        for var in self._cached_variables:
            if getattr(self, var):
                variables[var] = getattr(self, var)
                if isinstance(variables[var], UUID):
                    variables[var] = str(variables[var])

        with open(self.cache_path / "variables.json", "w", encoding="utf-8") as f:
            json.dump(variables, f)

    def get_access_token_from_cache(self) -> Optional[str]:
        """Retrieve access token from cache if valid, else return None."""
        # Token cache file location - use repo directory for easier debugging
        token_cache_path = self.cache_path / "evo_token_cache.json"
        # Try to load cached token first

        logger.debug(f"Checking for cached token at {token_cache_path}")
        if token_cache_path.exists():
            try:
                with open(token_cache_path, 'r') as f:
                    token_data = json.load(f)

                logger.debug("Found cached token, verifying its validity...")
                access_token = token_data.get('access_token')
                if not access_token:
                    raise ValueError("Access token not found in cache")

                # Verify token is not expired
                jwt.decode(access_token, options={"verify_signature": False, "verify_exp": True})

                logger.debug("Cached token appears to be valid and not expired.")
                return access_token
                
            except Exception as e:
                # Token expired or invalid, need to re-authenticate
                logger.info(f"Cached token invalid or expired: {type(e).__name__} - {str(e)}")
        else:
            logger.info(f"No cached token found at {token_cache_path}")
        return None
    
    def save_access_token_to_cache(self, access_token: str) -> None:
        """Save access token to cache file."""
        token_cache_path = self.cache_path / "evo_token_cache.json"
        with open(token_cache_path, 'w') as f:
            json.dump({'access_token': access_token}, f)
        logger.info(f"Access token saved to cache at {token_cache_path}")
    
    def get_transport(self) -> AioTransport:
        if self.transport is not None:
            return self.transport
        from evo_mcp import __dist_name__, __version__
        self.transport = AioTransport(user_agent=f"{__dist_name__}/{__version__}")
        return self.transport

    async def get_access_token_via_user_login(self) -> str:
        # Set up OAuth authentication (following SDK example pattern)
        redirect_url = os.getenv("EVO_REDIRECT_URL")
        client_id = os.getenv("EVO_CLIENT_ID")
        issuer_url = os.getenv('ISSUER_URL')
        if not client_id:
            raise ValueError("EVO_CLIENT_ID environment variable is required")

        logger.info("Starting OAuth login flow...")
        transport = self.get_transport()
        oauth_connector = OAuthConnector(transport=transport, client_id=client_id, base_uri=issuer_url)
        auth_code_authorizer = AuthorizationCodeAuthorizer(
            oauth_connector=oauth_connector,
            redirect_url=redirect_url,
            scopes=EvoScopes.all_evo
        )
        
        # Perform OAuth login (this gets the access token)
        await auth_code_authorizer.login()
        logger.info("OAuth login completed")
        
        # Extract access token from the Authorization header
        headers = await auth_code_authorizer.get_default_headers()
        auth_header = headers.get('Authorization', '')    
        if auth_header.startswith('Bearer '):
            return auth_header[7:]  # Remove 'Bearer ' prefix         
        else:
            logger.error("ERROR: Could not extract access token from headers")
            raise ValueError("Failed to obtain access token from OAuth login")
    
    async def get_authorizer(self) -> AccessTokenAuthorizer:
        """Create an OAuth authorizer based on environment variables."""
        access_token = self.get_access_token_from_cache()
        
        # If no valid cached token, do full OAuth login
        if access_token is None:
            access_token = await self.get_access_token_via_user_login()
            self.save_access_token_to_cache(access_token)

        authorizer = AccessTokenAuthorizer(
            access_token=access_token
        )
            
        return authorizer
    
    
    async def initialize(self):
        """Initialize connection to Evo platform with OAuth authentication."""
        if self._initialized and self.get_access_token_from_cache() is not None:
            return
        
        # Get configuration from environment variables
        discovery_url = os.getenv("EVO_DISCOVERY_URL")
        

        self.load_variables_from_cache()
        
        transport = self.get_transport()
        authorizer = await self.get_authorizer()
        
        # Use Discovery API to get organization and hub details
        discovery_connector = APIConnector(discovery_url, transport, authorizer)
        self.discovery_client = DiscoveryAPIClient(discovery_connector)
        
        if not self.org_id or not self.hub_url:
            # Get default organization
            organizations = await self.discovery_client.list_organizations()
            
            if not organizations:
                raise ValueError("The authenticated user does not have access to any Evo instances. They may need to contact their administrator to be added to an Evo instance or to resolve any licensing issues.")
        
            org = organizations[0]
            self.org_id = org.id

            if not org.hubs:
                raise ValueError(
                    f"Organization {self.org_id} has no hubs configured. "
                    f"This may indicate a licensing or permission issue."
                )

            # There is only one hub for an organization
            self.hub_url = org.hubs[0].url
        
        # Create connector for the hub
        self.connector = APIConnector(self.hub_url, transport, authorizer)
        
        # Create workspace client
        self.workspace_client = WorkspaceAPIClient(self.connector, self.org_id)
        self._initialized = True

        self.save_variables_to_cache()
    

    async def get_object_client(self, workspace_id: UUID) -> ObjectAPIClient:
        """Get or create an object client for a workspace."""
        workspace = await self.workspace_client.get_workspace(workspace_id)
        environment = workspace.get_environment()
        return ObjectAPIClient(environment, self.connector)

    async def get_file_client(self, workspace_id: UUID) -> FileAPIClient:
        """Get or create a file client for a workspace."""
        workspace = await self.workspace_client.get_workspace(workspace_id)
        environment = workspace.get_environment()
        return FileAPIClient(environment, self.connector)

    async def switch_instance(self, org_id: UUID, hub_url: str):
        """Switch to a different instance and recreate clients.
        
        Args:
            org_id: The organization/instance UUID to switch to
            hub_url: The hub URL for the new instance
        """
        self.org_id = org_id
        self.hub_url = hub_url
        
        # Recreate connector for the new hub URL
        # Reuse existing transport and authorizer from the current connector
        self.connector = APIConnector(
            self.hub_url,
            self.connector._transport,
            self.connector._authorizer
        )
        
        # Recreate workspace client with new connector and org_id
        self.workspace_client = WorkspaceAPIClient(self.connector, self.org_id)
        
        self.save_variables_to_cache()
    
    
evo_context = EvoContext()


async def ensure_initialized():
    """Ensure Evo context is initialized before any tool is called."""
    await evo_context.initialize()
