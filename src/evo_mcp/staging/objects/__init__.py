# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Staged object types with discoverable interactions.

Object type modules register themselves with ``staged_object_type_registry``
when imported. All modules are loaded eagerly at package import time.
The circular dependency between ``session`` and ``staging`` is resolved via
``staging.runtime``, a leaf module that holds runtime-injected references.

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
# Safe because these modules import from staging.runtime (a leaf),
# not from evo_mcp.session or evo_mcp.staging.service directly.
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
