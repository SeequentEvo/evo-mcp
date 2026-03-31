# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Client-delegated auth context (one per MCP session)."""

import logging
from uuid import UUID

from evo.common import APIConnector
from evo.oauth import AccessTokenAuthorizer
from evo.workspaces import WorkspaceAPIClient

from .base import EvoContextBase, _CACHE_PATH

logger = logging.getLogger(__name__)


class DelegatedAuthContext(EvoContextBase):
    """Per-client context created from a FastMCP OIDCProxy token.

    Each authenticated MCP client gets its own ``DelegatedAuthContext``
    instance, keyed by the MCP session ID.  When a token refreshes within
    the same session the access token is hot-swapped on the existing
    authorizer so that instance/workspace selection is preserved.
    """

    def __init__(self, client_session_id: str, access_token: str):
        super().__init__()
        self.client_session_id = client_session_id
        self._access_token = access_token
        self.cache_path = _CACHE_PATH / f"client_session_id-{client_session_id}"

    async def initialize(self) -> None:
        """Build API clients from the delegated access token."""
        if self.connector is not None:
            return  # already initialized
        authorizer = AccessTokenAuthorizer(access_token=self._access_token)
        await self.discover_and_build(authorizer)

    def update_access_token(self, new_token: str) -> None:
        """Hot-swap the access token on all existing API connectors.

        This keeps the instance/workspace selection intact when a token
        is refreshed within the same MCP session.
        """
        self._access_token = new_token
        if self.connector is not None:
            # AccessTokenAuthorizer stores the token as a plain string
            self.connector._authorizer._access_token = new_token

    async def switch_instance(self, org_id: UUID, hub_url: str) -> None:
        self.org_id = org_id
        self.hub_url = hub_url
        self.connector = APIConnector(
            hub_url, self.connector._transport, self.connector._authorizer
        )
        self.workspace_client = WorkspaceAPIClient(self.connector, org_id)
