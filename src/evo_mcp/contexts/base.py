# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Abstract base class for Evo context objects."""

import logging
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional
from uuid import UUID

from evo.aio import AioTransport
from evo.common import APIConnector
from evo.discovery import DiscoveryAPIClient
from evo.files import FileAPIClient
from evo.objects import ObjectAPIClient
from evo.oauth import AccessTokenAuthorizer
from evo.workspaces import WorkspaceAPIClient

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_CACHE_PATH = _REPO_ROOT / ".cache"
if not _CACHE_PATH.exists():
    _CACHE_PATH.mkdir()


class EvoContextBase(ABC):
    """Shared interface for Evo context objects.

    Holds the Evo API clients and org metadata directly as instance attributes.
    Tools call ``get_evo_context()`` to obtain an initialized instance, then
    access attributes and helpers without knowing which auth mode is active.
    """

    def __init__(self):
        self.transport: Optional[AioTransport] = None
        self.cache_path: Path = _CACHE_PATH
        self.connector: Optional[APIConnector] = None
        self.workspace_client: Optional[WorkspaceAPIClient] = None
        self.discovery_client: Optional[DiscoveryAPIClient] = None
        self.org_id: Optional[UUID] = None
        self.hub_url: Optional[str] = None

    # -- Abstract contract --------------------------------------------------

    @abstractmethod
    async def initialize(self) -> None:
        """Ensure the context is ready for API calls."""

    @abstractmethod
    async def switch_instance(self, org_id: UUID, hub_url: str) -> None:
        """Switch to a different Evo instance."""

    # -- Shared helpers -----------------------------------------------------

    def get_transport(self) -> AioTransport:
        if self.transport is not None:
            return self.transport
        from evo_mcp import __dist_name__, __version__
        self.transport = AioTransport(user_agent=f"{__dist_name__}/{__version__}")
        return self.transport

    async def discover_and_build(
        self,
        authorizer: AccessTokenAuthorizer,
        *,
        seed_org_id: Optional[UUID] = None,
        seed_hub_url: Optional[str] = None,
    ) -> None:
        """Populate this context by discovering org/hub and building clients.

        If *seed_org_id* and *seed_hub_url* are provided (e.g. from cache)
        they are reused; otherwise the Discovery API is queried.
        """
        discovery_url = os.getenv("EVO_DISCOVERY_URL")
        transport = self.get_transport()

        discovery_connector = APIConnector(discovery_url, transport, authorizer)
        self.discovery_client = DiscoveryAPIClient(discovery_connector)

        self.org_id = seed_org_id
        self.hub_url = seed_hub_url

        if not self.org_id or not self.hub_url:
            organizations = await self.discovery_client.list_organizations()
            if not organizations:
                raise ValueError(
                    "The authenticated user does not have access to any Evo instances. "
                    "They may need to contact their administrator to be added to an "
                    "Evo instance or to resolve any licensing issues."
                )
            org = organizations[0]
            self.org_id = org.id
            if not org.hubs:
                raise ValueError(
                    f"Organization {self.org_id} has no hubs configured. "
                    f"This may indicate a licensing or permission issue."
                )
            self.hub_url = org.hubs[0].url

        self.connector = APIConnector(self.hub_url, transport, authorizer)
        self.workspace_client = WorkspaceAPIClient(self.connector, self.org_id)

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
