# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Client-delegated auth context (one per MCP session)."""

import logging
import tempfile
from pathlib import Path

from evo.oauth import AccessTokenAuthorizer

from evo_mcp.contexts.helpers import get_client_session_upstream_access_token

from .base import EvoContextBase

logger = logging.getLogger(__name__)


class DelegatedAuthContext(EvoContextBase):
    """Per-client context created from a FastMCP OIDCProxy token.

    Each authenticated MCP client gets its own ``DelegatedAuthContext``
    instance, keyed by the MCP session ID.  When a token refreshes within
    the same session, ``initialize`` is called again with the new token —
    it rebuilds the API clients from scratch while preserving the selected
    instance/workspace via seed values.
    """

    def __init__(self, client_session_id: str):
        super().__init__()
        self.client_session_id = client_session_id
        self._access_token = None
        # Temp dir for SDK Cache used by object_build_tools — cleaned up on GC
        self._temp_dir = tempfile.TemporaryDirectory(prefix=f"evo-mcp-{client_session_id[:8]}-")
        self.cache_path = Path(self._temp_dir.name)
        # TODO: Consider using redis-based cache backend to share session data across multiple MCP server instances or to deploy in ephemeral environments (e.g. Kubernetes)

    def cleanup(self) -> None:
        """Remove the temporary cache directory."""
        self._temp_dir.cleanup()

    async def get_authorizer(self) -> AccessTokenAuthorizer:
        return AccessTokenAuthorizer(access_token=self._access_token)

    async def initialize(self) -> None:
        """Build (or rebuild) API clients from the given access token.

        The current ``org_id`` and ``hub_url`` are passed as seeds so the
        Discovery HTTP call is skipped on rebuilds.
        """
        upstream_access_token = get_client_session_upstream_access_token()
        if upstream_access_token == self._access_token and self.connector is not None:
            return  # Same token and already initialized — skip rebuild
        self._access_token = upstream_access_token

        await self.discover_and_build(
            seed_org_id=self.org_id,
            seed_hub_url=self.hub_url,
        )
