# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Session-scoped object registry entry model."""

from dataclasses import dataclass
from typing import Any, Literal

# Object type is an open string — mirrors staging.models.ObjectType
ObjectType = str

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
    workspace_id: str | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "object_type": self.object_type,
            "status": self.status,
            "workspace_id": self.workspace_id,
        }
