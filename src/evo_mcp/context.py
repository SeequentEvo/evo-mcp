"""
Configuration and Context Management for Evo SDK.

This module handles connection initialization, OAuth authentication,
and client management for the Evo platform.
"""

import os
import json
from pathlib import Path
from typing import Optional
from uuid import UUID

from dotenv import load_dotenv
from evo.aio import AioTransport
from evo.oauth import OAuthConnector, AuthorizationCodeAuthorizer, AccessTokenAuthorizer, EvoScopes
from evo.discovery import DiscoveryAPIClient
from evo.common import APIConnector

from evo.objects import ObjectAPIClient
from evo.workspaces import WorkspaceAPIClient


# Load environment variables from .env file
# Look for .env in the project root (parent of src directory)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


class EvoContext:
    """Maintains Evo SDK connection state and clients."""
    
    def __init__(self):
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

        self.log_path = repo_root / ".evo_mcp_debug.log"

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

    
    async def initialize(self):
        """Initialize connection to Evo platform with OAuth authentication."""
        if self._initialized:
            return
        
        # Get configuration from environment variables
        client_id = os.getenv("EVO_CLIENT_ID")
        redirect_url = os.getenv("EVO_REDIRECT_URL")
        discovery_url = os.getenv("EVO_DISCOVERY_URL")
        issuer_url = os.getenv('ISSUER_URL')

        self.load_variables_from_cache()
        
        if not client_id:
            raise ValueError("EVO_CLIENT_ID environment variable is required")
        
        # Set up OAuth authentication (following SDK example pattern)
        transport = AioTransport(user_agent="evo-mcp")
        oauth_connector = OAuthConnector(transport=transport, client_id=client_id, base_uri=issuer_url)
        
        # Token cache file location - use repo directory for easier debugging
        token_cache_path = self.cache_path / "evo_token_cache.json"
        
        # Simple file logging helper
        def log(msg: str):
            with open(self.log_path, 'a') as f:
                from datetime import datetime
                f.write(f"{datetime.now().isoformat()} - {msg}\n")
        
        authorizer = None
        
        # Try to load cached token first
        log(f"Checking for cached token at {token_cache_path}")
        if token_cache_path.exists():
            try:
                with open(token_cache_path, 'r') as f:
                    token_data = json.load(f)
                
                log("Found cached token, attempting to use it")
                # Use cached access token - AccessTokenAuthorizer just takes the token directly
                authorizer = AccessTokenAuthorizer(
                    access_token=token_data.get('access_token')
                )
                
                # Validate token by making a test API call
                # TODO: faster way to validate it?
                test_connector = APIConnector(discovery_url, transport, authorizer)
                test_client = DiscoveryAPIClient(test_connector)
                await test_client.list_organizations()
                # Token is valid!
                log("Cached token is valid, using it!")
                
            except Exception as e:
                # Token expired or invalid, need to re-authenticate
                log(f"Cached token invalid or expired: {type(e).__name__} - {str(e)}")
                authorizer = None
        else:
            log(f"No cached token found at {token_cache_path}")
        
        # If no valid cached token, do full OAuth login
        if authorizer is None:
            log("Starting OAuth login flow...")
            authorizer = AuthorizationCodeAuthorizer(
                oauth_connector=oauth_connector,
                redirect_url=redirect_url,
                scopes=EvoScopes.all_evo
            )
            
            # Perform OAuth login (this gets the access token)
            await authorizer.login()
            log("OAuth login completed")
            
            # Cache the token for future sessions
            try:
                # Extract access token from the Authorization header
                headers = await authorizer.get_default_headers()
                auth_header = headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    access_token = auth_header[7:]  # Remove 'Bearer ' prefix
                    with open(token_cache_path, 'w') as f:
                        json.dump({'access_token': access_token}, f)
                    log(f"Token cached successfully to {token_cache_path}")
                else:
                    log("ERROR: Could not extract access token from headers")
            except Exception as e:
                # Token caching is optional, don't fail if it doesn't work
                log(f"ERROR caching token: {type(e).__name__} - {str(e)}")
        
        # Use Discovery API to get organization and hub details
        discovery_connector = APIConnector(discovery_url, transport, authorizer)
        self.discovery_client = DiscoveryAPIClient(discovery_connector)
        
        # Get default organization
        organizations = await self.discovery_client.list_organizations()
        
        if not organizations:
            raise ValueError("No organizations found for the authenticated user")
        
        if not self.org_id or not self.hub_url:
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
    
    
evo_context = EvoContext()


async def ensure_initialized():
    """Ensure Evo context is initialized before any tool is called."""
    if not evo_context._initialized:
        await evo_context.initialize()
