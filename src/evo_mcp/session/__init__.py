# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""evo_mcp session sub-package.

Provides the session-scoped object registry that maps user-facing
names to internal staged objects.  Each EvoContext owns its own
ObjectRegistry instance for session isolation.

Usage::

    evo_context = await get_evo_context()
    evo_context.object_registry.register(name=..., ...)
"""

from evo_mcp.session.models import RegistryEntry, RegistryStatus
from evo_mcp.session.registry import ObjectRegistry
from evo_mcp.session.resolver import DuplicateNameError, ObjectResolver, ResolutionError

__all__ = [
    "DuplicateNameError",
    "ObjectRegistry",
    "ObjectResolver",
    "RegistryEntry",
    "RegistryStatus",
    "ResolutionError",
]
