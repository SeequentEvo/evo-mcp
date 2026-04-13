# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Shared support helpers for Evo MCP tool modules."""

import asyncio
from typing import Annotated, Any
from uuid import UUID

from evo.common import IFeedback, StaticContext
from evo.common.utils import Cache
from evo.objects.typed import EpsgCode
from evo.widgets import get_portal_url, get_viewer_url
from fastmcp import Context
from pydantic import Field

from evo_mcp.context import ensure_initialized, evo_context


VariogramObjectId = Annotated[
    str,
    Field(
        description=("UUID of the variogram object to use for kriging."),
    ),
]


class MCPFeedback(IFeedback):
    """IFeedback implementation that forwards progress to a FastMCP Context.

    Bridges the synchronous IFeedback.progress() contract to FastMCP's async
    ctx.report_progress() by scheduling the coroutine on the running event loop.
    Progress values (0.0–1.0) are scaled to a 0–100 range.
    """

    def __init__(self, ctx: Context) -> None:
        self._ctx = ctx

    def progress(self, progress: float, message: str | None = None) -> None:
        asyncio.ensure_future(self._ctx.report_progress(progress * 100, 100, message))


def require_object_role(
    obj: Any,
    expected_types: type[Any] | tuple[type[Any], ...],
    role: str,
    expected_label: str,
) -> None:
    if isinstance(obj, expected_types):
        return

    actual_type = type(obj).__name__
    raise ValueError(f"{role} object must be {expected_label}; got {actual_type}.")


def coerce_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric; got {value!r}.") from exc


def extract_crs(obj: Any) -> Any:
    if hasattr(obj, "coordinate_reference_system"):
        return getattr(obj, "coordinate_reference_system")

    if hasattr(obj, "as_dict"):
        document = obj.as_dict()
        return document.get("coordinate_reference_system")

    return None


def format_crs(crs: Any) -> str:
    if crs is None or crs == "unspecified":
        return "unspecified"

    if isinstance(crs, EpsgCode):
        return str(crs)

    if isinstance(crs, str):
        return crs.strip() or "unspecified"

    if isinstance(crs, dict):
        if "epsg_code" in crs:
            return f"EPSG:{crs['epsg_code']}"
        if "ogc_wkt" in crs:
            return str(crs["ogc_wkt"]).strip() or "unspecified"

    return str(crs)


def schema_label(obj: Any) -> str | None:
    metadata = getattr(obj, "metadata", None)
    schema_id = getattr(metadata, "schema_id", None)
    sub_classification = getattr(schema_id, "sub_classification", None)
    if sub_classification:
        return str(sub_classification)
    return None


async def get_workspace_environment(workspace_id: str) -> Any:
    await ensure_initialized()

    workspace_uuid = UUID(workspace_id)
    workspace = await evo_context.workspace_client.get_workspace(workspace_uuid)
    return workspace.get_environment()


async def get_workspace_context(workspace_id: str) -> StaticContext:
    environment = await get_workspace_environment(workspace_id)
    return StaticContext.from_environment(
        environment,
        evo_context.connector,
        Cache(evo_context.cache_path),
    )


def build_links_from_metadata(environment: Any, object_id: str) -> dict[str, str]:
    return {
        "portal_url": get_portal_url(
            org_id=str(environment.org_id),
            workspace_id=str(environment.workspace_id),
            object_id=object_id,
            hub_url=environment.hub_url,
        ),
        "viewer_url": get_viewer_url(
            org_id=str(environment.org_id),
            workspace_id=str(environment.workspace_id),
            object_ids=object_id,
            hub_url=environment.hub_url,
        ),
    }


def normalize_crs(
    coordinate_reference_system: str | None,
    *,
    none_value: str | None = "unspecified",
) -> str | None:
    """Normalize a CRS string.

    Returns *none_value* for ``None``, empty, or ``"unspecified"`` inputs.
    Canonicalizes ``EPSG:`` prefixes.
    """
    if coordinate_reference_system is None:
        return none_value

    normalized = coordinate_reference_system.strip()
    if not normalized or normalized == "unspecified":
        return none_value

    if normalized.upper().startswith("EPSG:"):
        return f"EPSG:{normalized.split(':', 1)[1].strip()}"

    return normalized


__all__ = [
    "VariogramObjectId",
    "require_object_role",
    "coerce_float",
    "extract_crs",
    "format_crs",
    "schema_label",
    "get_workspace_environment",
    "get_workspace_context",
    "build_links_from_metadata",
    "normalize_crs",
]
