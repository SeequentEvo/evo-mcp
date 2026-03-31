# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for spatial validation workflows.

Validates CRS compatibility between staged objects using the session
registry. No Evo API calls required.
"""

from __future__ import annotations

from typing import Any

from evo_mcp.session import object_registry, ResolutionError
from evo_mcp.utils.tool_support import (
    extract_crs,
    format_crs,
)


def _compare_crs(source_crs: Any, target_crs: Any) -> str:
    source_label = format_crs(source_crs)
    target_label = format_crs(target_crs)

    if source_label == "unspecified" or target_label == "unspecified":
        return "unknown"

    if source_label == target_label:
        return "compatible"

    return "mismatch"


def register_spatial_tools(mcp) -> None:
    """Register spatial validation tools with the FastMCP server."""

    @mcp.tool()
    async def spatial_validate_crs_and_units(
        source_name: str,
        target_name: str,
    ) -> dict[str, Any]:
        """Validate CRS compatibility between a source point set and a target block model.

        Resolves both objects from the session registry and compares their
        coordinate reference systems. No Evo API call required — works
        entirely from staged payloads.

        Args:
            source_name: Name of the source object (point set) in the session.
            target_name: Name of the target object (block model) in the session.
        """
        try:
            source_entry, source_payload = object_registry.get_payload(
                name=source_name, object_type="point_set"
            )
        except (ResolutionError, Exception) as exc:
            raise ValueError(
                f"Could not resolve source '{source_name}' as a point set."
            ) from exc

        try:
            target_entry, target_payload = object_registry.get_payload(
                name=target_name, object_type="regular_block_model"
            )
        except (ResolutionError, Exception):
            try:
                target_entry, target_payload = object_registry.get_payload(
                    name=target_name, object_type="block_model"
                )
            except (ResolutionError, Exception) as exc:
                raise ValueError(
                    f"Could not resolve target '{target_name}' as a block model."
                ) from exc

        source_crs = extract_crs(source_payload)
        target_crs = extract_crs(target_payload)
        status = _compare_crs(source_crs, target_crs)

        if status == "compatible":
            message = "Source and target CRS match."
        elif status == "unknown":
            message = "At least one CRS is unspecified. Manual confirmation is required before execution."
        else:
            message = "Source and target CRS do not match. Resolve this before running kriging."

        return {
            "status": status,
            "message": message,
            "source": {
                "name": source_name,
                "object_type": source_entry.object_type,
                "coordinate_reference_system": format_crs(source_crs),
            },
            "target": {
                "name": target_name,
                "object_type": target_entry.object_type,
                "coordinate_reference_system": format_crs(target_crs),
            },
            "unit_context": {
                "guidance": (
                    "Search-neighborhood ranges should use the same coordinate units as the resolved CRS."
                )
            },
        }
