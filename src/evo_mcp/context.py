# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Configuration and Context Management for Evo SDK.

This module handles connection initialization, OAuth authentication,
and client management for the Evo platform.

Authentication modes (controlled by CLIENT_DELEGATED_AUTH and AUTH_METHOD):

- CLIENT_DELEGATED_AUTH=true (HTTP transport only):
  Tokens come from FastMCP's OIDCProxy auth layer — one per connected MCP client,
  managed by the framework. Each user authenticates with their own Bentley account.
  No manual OAuth or token caching needed. AUTH_METHOD is not used in this mode.

- CLIENT_DELEGATED_AUTH=false (default, any transport):
  Single-user mode. AUTH_METHOD controls how the server authenticates:
  - native_app:          Interactive browser-based OAuth (AuthorizationCodeAuthorizer).
                         Token is cached to disk and reused until expiry.
  - client_credentials:  Non-interactive service token (ClientCredentialsAuthorizer).
                         Requires EVO_CLIENT_ID + EVO_CLIENT_SECRET.
"""

import logging
import os
import json
import jwt
from pathlib import Path
from typing import Optional
from uuid import UUID

from dotenv import load_dotenv
from evo.aio import AioTransport
from evo.oauth import OAuthConnector, AuthorizationCodeAuthorizer, AccessTokenAuthorizer, EvoScopes, ClientCredentialsAuthorizer
from evo.discovery import DiscoveryAPIClient
from evo.common import APIConnector

from evo.files import FileAPIClient
from evo.objects import ObjectAPIClient
from evo.workspaces import WorkspaceAPIClient

import hashlib


# Load environment variables from .env file
# Look for .env in the project root (parent of src directory)
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# Set up local logger for this module
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if os.environ.get("DEBUG") == "1" else logging.INFO)


class EvoSession:
    """Per-user session state for Evo API clients.

    In client-delegated mode (CLIENT_DELEGATED_AUTH=true), different users have different
    access tokens and may belong to different organizations. This class holds
    the per-user API clients and organization state.
    In server-managed mode (CLIENT_DELEGATED_AUTH=false), a single shared instance is used.
    """

    def __init__(self):
        self.connector: Optional[APIConnector] = None
        self.workspace_client: Optional[WorkspaceAPIClient] = None
        self.discovery_client: Optional[DiscoveryAPIClient] = None
        self.org_id: Optional[UUID] = None
        self.hub_url: Optional[str] = None


class EvoContext:
    """Maintains Evo SDK connection state and clients.

    Supports two modes:
    - Server-managed (CLIENT_DELEGATED_AUTH=false): State is cached globally after first
      initialization. All requests share one token and one session.
    - Client-delegated (CLIENT_DELEGATED_AUTH=true, HTTP only): Per-session state is keyed
      by the user's access token from FastMCP's OIDCProxy. Tools access the
      current session's clients transparently via properties.
    """
    
    def __init__(self):
        self.transport: Optional[AioTransport] = None
        self._initialized: bool = False
        repo_root = Path(__file__).parent.parent.parent
        self.cache_path = repo_root / ".cache"
        if not self.cache_path.exists():
            self.cache_path.mkdir()

        # Server-managed mode: one shared session
        self._stdio_session = EvoSession()

        # Client-delegated mode: per-token session cache
        self._sessions: dict[str, EvoSession] = {}

    def _current_session(self) -> EvoSession:
        """Get the session for the current request.

        In client-delegated mode (CLIENT_DELEGATED_AUTH=true), returns the session keyed
        by the current user's token. Otherwise returns the single shared session.
        """
        token = self._get_fastmcp_access_token()
        if token is not None:
            token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
            session = self._sessions.get(token_hash)
            if session is not None:
                return session
        return self._stdio_session

    @property
    def connector(self) -> Optional[APIConnector]:
        return self._current_session().connector

    @connector.setter
    def connector(self, value):
        self._current_session().connector = value

    @property
    def workspace_client(self) -> Optional[WorkspaceAPIClient]:
        return self._current_session().workspace_client

    @workspace_client.setter
    def workspace_client(self, value):
        self._current_session().workspace_client = value

    @property
    def discovery_client(self) -> Optional[DiscoveryAPIClient]:
        return self._current_session().discovery_client

    @discovery_client.setter
    def discovery_client(self, value):
        self._current_session().discovery_client = value

    @property
    def org_id(self) -> Optional[UUID]:
        return self._current_session().org_id

    @org_id.setter
    def org_id(self, value):
        self._current_session().org_id = value

    @property
    def hub_url(self) -> Optional[str]:
        return self._current_session().hub_url

    @hub_url.setter
    def hub_url(self, value):
        self._current_session().hub_url = value


    def load_variables_from_cache(self):
        """Load cached variables (org_id, hub_url) into the STDIO session."""
        try:
            with open(self.cache_path / "variables.json", encoding="utf-8") as f:
                variables = json.load(f)
        except FileNotFoundError:
            return

        if "org_id" in variables:
            self._stdio_session.org_id = UUID(variables["org_id"])
        if "hub_url" in variables:
            self._stdio_session.hub_url = variables["hub_url"]


    def save_variables_to_cache(self):
        """Save STDIO session variables to cache file."""
        variables = {}
        if self._stdio_session.org_id:
            variables["org_id"] = str(self._stdio_session.org_id)
        if self._stdio_session.hub_url:
            variables["hub_url"] = self._stdio_session.hub_url

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

    @staticmethod
    def _get_fastmcp_access_token() -> Optional[str]:
        """Get the upstream access token from FastMCP's auth context.

        When running with CLIENT_DELEGATED_AUTH=true (HTTP + OIDCProxy), FastMCP
        handles OAuth and stores the upstream Bentley IMS token per request.
        Returns None in server-managed mode or when no authenticated user is present.
        """
        try:
            from fastmcp.server.dependencies import get_access_token
            token = get_access_token()
            if token is not None:
                return token.token
        except (ImportError, RuntimeError):
            pass
        return None
    
    async def get_access_token_via_client_credentials(self) -> str:
        logger.debug("Obtaining a new service token")
        client_id = os.getenv("EVO_CLIENT_ID")
        client_secret = os.getenv("EVO_CLIENT_SECRET")
        issuer_url = os.getenv('ISSUER_URL')
        if not client_id or not client_secret:
            raise ValueError("EVO_CLIENT_ID and EVO_CLIENT_SECRET environment variables are required with client credentials authentication method")
        
        transport = self.get_transport()
        oauth_connector = OAuthConnector(transport=transport, client_id=client_id, client_secret=client_secret, base_uri=issuer_url)
        authorizer = ClientCredentialsAuthorizer(oauth_connector, scopes=EvoScopes.all_evo)
        
        headers = await authorizer.get_default_headers()
        auth_header = headers.get('Authorization', '')

        if auth_header.startswith('Bearer '):
            return auth_header[7:]  # Remove 'Bearer ' prefix         
        else:
            logger.error("ERROR: Could not extract access token from headers")
            raise ValueError("Failed to obtain access token from OAuth login")

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
        """Create an OAuth authorizer for Evo API calls.

        In client-delegated mode (CLIENT_DELEGATED_AUTH=true), the access token comes from
        FastMCP's OIDCProxy auth context — no manual OAuth or token caching needed.
        In server-managed mode, falls back to AUTH_METHOD-based auth with file caching.
        """
        # Client-delegated mode: token provided per-request via the Authorization header
        fastmcp_token = self._get_fastmcp_access_token()
        if fastmcp_token is not None:
            logger.debug("Using access token from FastMCP auth context")
            return AccessTokenAuthorizer(access_token=fastmcp_token)

        # Server-managed mode: AUTH_METHOD controls how we obtain the token
        access_token = self.get_access_token_from_cache()

        if access_token is None:
            auth_method = os.environ.get("AUTH_METHOD")
            if auth_method == "client_credentials":
                access_token = await self.get_access_token_via_client_credentials()
            else:
                access_token = await self.get_access_token_via_user_login()
            self.save_access_token_to_cache(access_token)

        return AccessTokenAuthorizer(access_token=access_token)
    
    
    async def initialize(self):
        """Initialize connection to Evo platform with OAuth authentication.

        In client-delegated mode (CLIENT_DELEGATED_AUTH=true), each request may come from a
        different user, so we maintain per-token session state. Sessions are cached
        by token hash so subsequent calls with the same token reuse existing clients.
        In server-managed mode (CLIENT_DELEGATED_AUTH=false), the initialized state is cached
        for the lifetime of the process.
        """
        fastmcp_token = self._get_fastmcp_access_token()
        is_client_delegated = fastmcp_token is not None

        if is_client_delegated:
            # Client-delegated: check if we already have a session for this token
            token_hash = hashlib.sha256(fastmcp_token.encode()).hexdigest()[:16]
            if token_hash in self._sessions:
                return
        else:
            # Server-managed: reuse cached state if valid
            if self._initialized and self.get_access_token_from_cache() is not None:
                return
        
        # Get configuration from environment variables
        discovery_url = os.getenv("EVO_DISCOVERY_URL")

        if not is_client_delegated:
            self.load_variables_from_cache()

        transport = self.get_transport()
        authorizer = await self.get_authorizer()

        # Create a new session for this user
        session = EvoSession()

        # Use Discovery API to get organization and hub details
        discovery_connector = APIConnector(discovery_url, transport, authorizer)
        session.discovery_client = DiscoveryAPIClient(discovery_connector)

        # In server-managed mode, try to reuse cached org/hub. In client-delegated mode,
        # load from the discovery API for each new user.
        if not is_client_delegated:
            session.org_id = self._stdio_session.org_id
            session.hub_url = self._stdio_session.hub_url

        if not session.org_id or not session.hub_url:
            organizations = await session.discovery_client.list_organizations()
            
            if not organizations:
                raise ValueError("The authenticated user does not have access to any Evo instances. They may need to contact their administrator to be added to an Evo instance or to resolve any licensing issues.")
        
            org = organizations[0]
            session.org_id = org.id

            if not org.hubs:
                raise ValueError(
                    f"Organization {session.org_id} has no hubs configured. "
                    f"This may indicate a licensing or permission issue."
                )

            session.hub_url = org.hubs[0].url
        
        # Create connector and workspace client
        session.connector = APIConnector(session.hub_url, transport, authorizer)
        session.workspace_client = WorkspaceAPIClient(session.connector, session.org_id)

        if is_client_delegated:
            self._sessions[token_hash] = session
            logger.debug("Created new session for token %s...", token_hash[:8])
        else:
            self._stdio_session = session
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
        session = self._current_session()
        session.org_id = org_id
        session.hub_url = hub_url
        
        # Recreate connector for the new hub URL
        # Reuse existing transport and authorizer from the current connector
        session.connector = APIConnector(
            session.hub_url,
            session.connector._transport,
            session.connector._authorizer
        )
        
        # Recreate workspace client with new connector and org_id
        session.workspace_client = WorkspaceAPIClient(session.connector, session.org_id)
        
        # Only persist to file cache in server-managed mode
        if self._get_fastmcp_access_token() is None:
            self.save_variables_to_cache()
    
    
evo_context = EvoContext()


async def ensure_initialized():
    """Ensure Evo context is initialized before any tool is called."""
    await evo_context.initialize()
