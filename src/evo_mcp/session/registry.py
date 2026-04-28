# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Session-scoped object registry.

Wraps the staging service and provides name-based object tracking.
Domain tools register objects after creation; downstream tools resolve
objects by name.  Users never see stage_ids.

Usage::

    from evo_mcp.session import object_registry

    # Domain tool creates an object, then registers it
    envelope = staging_service.stage_local_build(...)
    entry = object_registry.register(
        name="CU variogram",
        object_type="variogram",
        stage_id=envelope.stage_id,
    )
    # Downstream tool resolves by name
    entry, payload = object_registry.get_payload("CU variogram")
"""

from dataclasses import replace
from typing import Any

from evo_mcp.session.models import ObjectType, RegistryEntry
from evo_mcp.session.resolver import ObjectResolver, ResolutionError
from evo_mcp.staging.service import StagingService, now_iso

__all__ = [
    "ObjectRegistry",
    "ResolutionError",
    "object_registry",
]


class ObjectRegistry:
    """Session-scoped registry mapping user-facing names to staged objects.

    The registry sits between user-facing tools and the staging service:
    - **Register**: called by create/import tools after staging.
    - **Resolve**: called by inspect/compute tools to find objects by name.
    - **Publish**: called by publish/compute tools to auto-publish.

    All entries are in-memory for the session lifetime.
    """

    def __init__(
        self,
        staging_service: StagingService,
        resolver: ObjectResolver | None = None,
    ) -> None:
        self._staging = staging_service
        self._resolver = resolver or ObjectResolver()
        self._entries: dict[str, RegistryEntry] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(
        self,
        name: str,
        object_type: ObjectType,
        stage_id: str,
        workspace_id: str | None = None,
    ) -> RegistryEntry:
        """Register an object after it has been staged.

        If a name+type combination already exists, the new registration
        replaces the old one (latest-wins).
        """
        entry = RegistryEntry(
            name=name,
            object_type=object_type,
            stage_id=stage_id,
            status="staged",
            workspace_id=workspace_id,
            created_at=now_iso(),
        )
        key = self._make_key(name, object_type)
        self._entries[key] = entry
        return entry

    # ------------------------------------------------------------------
    # Resolution
    # ------------------------------------------------------------------

    def resolve(
        self,
        name: str | None = None,
        object_type: ObjectType | None = None,
    ) -> RegistryEntry:
        """Resolve an object reference by name and/or type.

        Raises ResolutionError if not found or ambiguous.
        """
        return self._resolver.resolve(self._entries, name, object_type)

    def get_payload(
        self,
        name: str | None = None,
        object_type: ObjectType | None = None,
    ) -> tuple[RegistryEntry, Any]:
        """Resolve an object and return its typed payload from staging.

        Returns (entry, typed_payload).
        """
        entry = self.resolve(name, object_type)
        _, payload = self._staging.get_stage_payload(entry.stage_id)
        return entry, payload

    # ------------------------------------------------------------------
    # Listing
    # ------------------------------------------------------------------

    def list_objects(
        self,
        object_type: ObjectType | None = None,
    ) -> list[RegistryEntry]:
        """List all registered objects, optionally filtered by type."""
        entries = list(self._entries.values())
        if object_type is not None:
            entries = [e for e in entries if e.object_type == object_type]
        return sorted(entries, key=lambda e: e.created_at)

    # ------------------------------------------------------------------
    # Publication tracking
    # ------------------------------------------------------------------

    def mark_published(
        self,
        name: str,
        object_type: ObjectType,
        workspace_id: str | None = None,
    ) -> RegistryEntry:
        """Update a registry entry after successful publication."""
        entry = self.resolve(name, object_type)
        updated = replace(
            entry,
            status="published",
            workspace_id=workspace_id or entry.workspace_id,
        )
        key = self._make_key(name, object_type)
        self._entries[key] = updated
        return updated

    def is_published(
        self,
        name: str,
        object_type: ObjectType | None = None,
    ) -> bool:
        """Check if an object has already been published."""
        try:
            entry = self.resolve(name, object_type)
            return entry.status == "published"
        except ResolutionError:
            return False

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _make_key(name: str, object_type: ObjectType) -> str:
        return f"{object_type}::{name.lower()}"

    def deregister(self, name: str, object_type: ObjectType | None = None) -> None:
        """Remove a registry entry by name (and optional type).

        Raises ResolutionError if not found.
        """
        entry = self.resolve(name, object_type)
        key = self._make_key(entry.name, entry.object_type)
        del self._entries[key]

    def clear(self) -> None:
        """Clear all entries. Used by test infrastructure."""
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


# Module-level singleton shared by all tool modules.
def _create_default_registry() -> ObjectRegistry:
    from evo_mcp.staging.service import staging_service

    return ObjectRegistry(staging_service)


object_registry = _create_default_registry()
