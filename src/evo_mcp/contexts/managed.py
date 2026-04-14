# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Server-managed auth context (single user, disk-cached tokens)."""

import json
import logging
import os
from pathlib import Path
from typing import Optional
from uuid import UUID

import jwt
from evo.oauth import (
    AccessTokenAuthorizer,
    AuthorizationCodeAuthorizer,
    ClientCredentialsAuthorizer,
    EvoScopes,
    OAuthConnector,
)

from .base import EvoContextBase

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_CACHE_PATH = _REPO_ROOT / ".cache"


class ManagedAuthContext(EvoContextBase):
    """Single-user context with server-managed OAuth.

    The server authenticates on behalf of one user via ``AUTH_METHOD``
    (``native_app`` or ``client_credentials``). Tokens and org/hub metadata
    are cached to disk so they survive restarts.
    """

    def __init__(self):
        super().__init__()
        self.initialized: bool = False
        self.cache_path = _CACHE_PATH
        self.cache_path.mkdir(parents=True, exist_ok=True)

    # -- Token cache --------------------------------------------------------

    def get_access_token_from_cache(self) -> Optional[str]:
        token_cache_path = self.cache_path / "evo_token_cache.json"
        logger.debug("Checking for cached token at %s", token_cache_path)
        if not token_cache_path.exists():
            logger.info("No cached token found at %s", token_cache_path)
            return None
        try:
            with open(token_cache_path, "r") as f:
                token_data = json.load(f)
            access_token = token_data.get("access_token")
            if not access_token:
                raise ValueError("Access token not found in cache")
            jwt.decode(access_token, options={"verify_signature": False, "verify_exp": True})
            logger.debug("Cached token appears to be valid and not expired.")
            return access_token
        except Exception as e:
            logger.info("Cached token invalid or expired: %s - %s", type(e).__name__, e)
            return None

    def save_access_token_to_cache(self, access_token: str) -> None:
        token_cache_path = self.cache_path / "evo_token_cache.json"
        with open(token_cache_path, "w") as f:
            json.dump({"access_token": access_token}, f)
        logger.info("Access token saved to cache at %s", token_cache_path)


    # -- Variables cache -----------------------------------------------------

    def load_variables_from_cache(self) -> None:
        try:
            with open(self.cache_path / "variables.json", encoding="utf-8") as f:
                variables = json.load(f)
        except FileNotFoundError:
            return
        if "org_id" in variables:
            self.org_id = UUID(variables["org_id"])
        if "hub_url" in variables:
            self.hub_url = variables["hub_url"]

    def save_variables_to_cache(self) -> None:
        variables: dict = {}
        if self.org_id:
            variables["org_id"] = str(self.org_id)
        if self.hub_url:
            variables["hub_url"] = self.hub_url
        with open(self.cache_path / "variables.json", "w", encoding="utf-8") as f:
            json.dump(variables, f)

    # -- OAuth flows --------------------------------------------------------

    async def get_access_token_via_client_credentials(self) -> str:
        logger.debug("Obtaining a new service token")
        client_id = os.getenv("EVO_CLIENT_ID")
        client_secret = os.getenv("EVO_CLIENT_SECRET")
        issuer_url = os.getenv("ISSUER_URL")
        if not client_id or not client_secret:
            raise ValueError(
                "EVO_CLIENT_ID and EVO_CLIENT_SECRET are required for client_credentials auth"
            )
        transport = self.get_transport()
        oauth_connector = OAuthConnector(
            transport=transport, client_id=client_id, client_secret=client_secret, base_uri=issuer_url
        )
        authorizer = ClientCredentialsAuthorizer(oauth_connector, scopes=EvoScopes.all_evo)
        headers = await authorizer.get_default_headers()
        auth_header = headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        raise ValueError("Failed to obtain access token via client credentials")

    async def get_access_token_via_user_login(self) -> str:
        redirect_url = os.getenv("EVO_REDIRECT_URL")
        client_id = os.getenv("EVO_CLIENT_ID")
        issuer_url = os.getenv("ISSUER_URL")
        if not client_id:
            raise ValueError("EVO_CLIENT_ID environment variable is required")

        logger.info("Starting OAuth login flow...")
        transport = self.get_transport()
        oauth_connector = OAuthConnector(transport=transport, client_id=client_id, base_uri=issuer_url)
        auth_code_authorizer = AuthorizationCodeAuthorizer(
            oauth_connector=oauth_connector,
            redirect_url=redirect_url,
            scopes=EvoScopes.all_evo,
        )
        await auth_code_authorizer.login()
        logger.info("OAuth login completed")

        headers = await auth_code_authorizer.get_default_headers()
        auth_header = headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]
        raise ValueError("Failed to obtain access token from OAuth login")

    async def get_authorizer(self) -> AccessTokenAuthorizer:
        access_token = self.get_access_token_from_cache()
        if access_token is None:
            auth_method = os.environ.get("AUTH_METHOD")
            if auth_method == "client_credentials":
                access_token = await self.get_access_token_via_client_credentials()
            else:
                access_token = await self.get_access_token_via_user_login()
            self.save_access_token_to_cache(access_token)
        return AccessTokenAuthorizer(access_token=access_token)

    # -- Lifecycle ----------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize or reuse the single shared context."""
        if self.initialized and self.get_access_token_from_cache() is not None:
            return

        self.load_variables_from_cache()

        await self.discover_and_build(
            seed_org_id=self.org_id,
            seed_hub_url=self.hub_url,
        )
        self.initialized = True
        self.save_variables_to_cache()

    async def switch_instance(self, org_id: UUID, hub_url: str) -> None:
        await super().switch_instance(org_id, hub_url)
        self.save_variables_to_cache()
