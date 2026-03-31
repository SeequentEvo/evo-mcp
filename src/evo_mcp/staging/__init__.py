# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""evo_mcp staging sub-package.

Public surface re-exported for convenience:

    from evo_mcp.staging import staging_service
    from evo_mcp.staging import StagedEnvelope, StageError
"""

from evo_mcp.staging.codecs import (
    BlockModelCodec,
    Codec,
    PointSetCodec,
    VariogramCodec,
    get_codec,
    variogram_structure_from_dict,
)
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
    "Codec",
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
    "PointSetCodec",
    "VariogramCodec",
    "BlockModelCodec",
    "get_codec",
    "variogram_structure_from_dict",
]
