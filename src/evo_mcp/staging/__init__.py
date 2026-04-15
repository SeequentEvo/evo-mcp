# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""evo_mcp staging sub-package.

Public surface re-exported for convenience::

    from evo_mcp.staging import staging_service
    from evo_mcp.staging import StagedEnvelope, StageError

Object types (interactions, registry) are accessed via
``evo_mcp.staging.objects`` and are lazy-loaded on first registry access
to avoid a circular import with ``evo_mcp.session``.
"""

from evo_mcp.staging.errors import (
    StageCapacityError,
    StageError,
    StageExpiredError,
    StageNotFoundError,
    StageRevisionConflictError,
    StageValidationError,
)
from evo_mcp.staging.models import ObjectType, StagedEnvelope, SourceType, StageStatus
from evo_mcp.staging.service import StagingService, staging_service

__all__ = [
    "staging_service",
    "StagingService",
    "StagedEnvelope",
    "ObjectType",
    "SourceType",
    "StageStatus",
    "StageError",
    "StageNotFoundError",
    "StageExpiredError",
    "StageValidationError",
    "StageRevisionConflictError",
    "StageCapacityError",
]
