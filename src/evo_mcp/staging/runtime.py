# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Staging runtime — dependency injection for registry and staging service.

This is a true leaf module (no evo_mcp runtime imports) that holds
references to the session object registry and the staging service.
Object type modules import ``get_registry`` and ``get_staging_service``
from here instead of importing directly from ``evo_mcp.session`` or
``evo_mcp.staging.service``, which would create circular dependencies.

Call ``configure(registry, staging_service)`` once at server startup
(before any tool is invoked) to wire the references:

    from evo_mcp.staging import runtime as staging_runtime
    staging_runtime.configure(object_registry, staging_service)

Type annotations use ``TYPE_CHECKING`` so that the type-checker sees
proper types without incurring any runtime import cost.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from evo_mcp.session.registry import ObjectRegistry
    from evo_mcp.staging.service import StagingService


_registry: "ObjectRegistry | None" = None
_staging_service: "StagingService | None" = None


def configure(registry: "ObjectRegistry", staging_service: "StagingService") -> None:
    """Wire runtime references. Must be called once at server startup."""
    global _registry, _staging_service
    _registry = registry
    _staging_service = staging_service


def get_registry() -> "ObjectRegistry":
    """Return the configured object registry, raising if not yet configured."""
    if _registry is None:
        raise RuntimeError(
            "Staging runtime is not configured. "
            "Call staging_runtime.configure(object_registry, staging_service) at startup."
        )
    return _registry  # type: ignore[return-value]


def get_staging_service() -> "StagingService":
    """Return the configured staging service, raising if not yet configured."""
    if _staging_service is None:
        raise RuntimeError(
            "Staging runtime is not configured. "
            "Call staging_runtime.configure(object_registry, staging_service) at startup."
        )
    return _staging_service  # type: ignore[return-value]
