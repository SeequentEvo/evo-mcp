# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Staged envelope model and enums. Payload stays internal in the store."""

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

ObjectType = Literal["point_set", "block_model", "regular_block_model", "variogram"]
SourceType = Literal["imported", "built_local", "cloned", "mutated"]
StageStatus = Literal["active", "published", "expired", "discarded"]

__all__ = [
    "ObjectType",
    "SourceType",
    "StageStatus",
    "StagedEnvelope",
]


@dataclass
class StagedEnvelope:
    """Lightweight metadata envelope returned to callers. No payload included."""

    stage_id: str
    object_type: ObjectType
    format_version: str
    workspace_id: str | None
    source_type: SourceType
    source_ref: dict[str, str | None]
    summary: dict[str, Any]
    status: StageStatus
    payload_revision: int
    created_at: str
    updated_at: str
    expires_at: str
    size_hints: dict[str, int | float | None] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
