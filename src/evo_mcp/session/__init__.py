# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""evo_mcp session sub-package.

Provides the session-scoped object registry that maps user-facing
names to internal staged objects.  This is the bridge between
domain-language tools and the staging infrastructure.

Usage::

    from evo_mcp.session import object_registry
"""

from evo_mcp.session.models import RegistryEntry, RegistryStatus
from evo_mcp.session.registry import ObjectRegistry, object_registry
from evo_mcp.session.resolver import ObjectResolver, ResolutionError

__all__ = [
    "ObjectRegistry",
    "ObjectResolver",
    "RegistryEntry",
    "RegistryStatus",
    "ResolutionError",
    "object_registry",
]
