# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Session-scoped object registry entry model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from evo_mcp.staging.models import ObjectType

RegistryStatus = Literal["staged", "published"]


@dataclass
class RegistryEntry:
    """Tracks a single object within the session registry.

    This is the internal bookkeeping record that maps a user-facing name
    to an internal stage_id.  Users never see this dataclass directly;
    tools return domain summaries instead.
    """

    name: str
    object_type: ObjectType
    stage_id: str
    status: RegistryStatus = "staged"
    source: str = "built_local"
    workspace_id: str | None = None
    published_object_id: str | None = None
    published_version_id: str | None = None
    summary: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "object_type": self.object_type,
            "status": self.status,
            "source": self.source,
            "workspace_id": self.workspace_id,
            "published_object_id": self.published_object_id,
            "summary": self.summary,
        }
