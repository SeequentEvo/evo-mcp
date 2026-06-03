# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Staged envelope model and enums. Payload stays internal in the store."""

from dataclasses import dataclass
from typing import Literal

# Object type is an open string — the registry is the authoritative source.
ObjectType = str
StageStatus = Literal["active", "published", "expired", "discarded"]

__all__ = [
    "ObjectType",
    "StageStatus",
    "StagedEnvelope",
]


@dataclass
class StagedEnvelope:
    """Lightweight metadata envelope returned to callers. No payload included."""

    stage_id: str
    object_type: ObjectType
    workspace_id: str | None
    source_ref: dict[str, str | None]
    status: StageStatus
    updated_at: str
    expires_at: str
