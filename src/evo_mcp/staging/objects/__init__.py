# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Staged object types with discoverable interactions.

Object type modules register themselves with ``staged_object_type_registry``
when imported. All modules are loaded eagerly at package import time.
Registry and staging service are accessed via ``get_evo_context()`` at
call time, so there is no circular import at module load.

Usage::

    from evo_mcp.staging.objects import staged_object_type_registry

    # Discover interactions for a variogram
    vtype = staged_object_type_registry.get("variogram")
    vtype.list_interactions()
"""

import evo_mcp.staging.objects.block_model  # noqa: F401
import evo_mcp.staging.objects.point_set  # noqa: F401
import evo_mcp.staging.objects.regular_block_model  # noqa: F401
import evo_mcp.staging.objects.search_neighborhood  # noqa: F401

# Eagerly load all object type modules so they self-register.
import evo_mcp.staging.objects.variogram  # noqa: F401
from evo_mcp.staging.objects.base import (
    EvoStagedObjectType,
    Interaction,
    StagedObjectType,
    StagedObjectTypeRegistry,
    staged_object_type_registry,
)

__all__ = [
    "EvoStagedObjectType",
    "Interaction",
    "StagedObjectType",
    "StagedObjectTypeRegistry",
    "staged_object_type_registry",
]
