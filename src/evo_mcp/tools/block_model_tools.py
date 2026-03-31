# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for local block-model design workflows.

Tools for designing and inspecting block model definitions.
Objects are tracked by name via the session registry.
"""

from __future__ import annotations

import math
from typing import Any

from evo.blockmodels.typed import RegularBlockModelData
from evo.common.typed import BoundingBox
from evo.objects.typed import (
    BlockModelData,
    Point3,
    Size3d,
    Size3i,
)

from evo_mcp.session import object_registry, ResolutionError
from evo_mcp.staging.errors import StageError
from evo_mcp.staging.service import staging_service
from evo_mcp.utils.tool_support import (
    normalize_crs,
)


def _coerce_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric; got {value!r}.") from exc


def _coerce_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an integer; got {value!r}.") from exc
    if parsed < 1:
        raise ValueError(f"{field_name} must be greater than or equal to 1.")
    return parsed


def _bounding_box_to_dict(bounding_box: BoundingBox) -> dict[str, float]:
    return {
        "x_min": float(bounding_box.x_min),
        "x_max": float(bounding_box.x_max),
        "y_min": float(bounding_box.y_min),
        "y_max": float(bounding_box.y_max),
        "z_min": float(bounding_box.z_min),
        "z_max": float(bounding_box.z_max),
    }


def _derive_regular_grid_definition(
    bounding_box: BoundingBox,
    block_size: Size3d,
) -> tuple[Point3, Size3i, BoundingBox]:
    extents = [
        bounding_box.x_max - bounding_box.x_min,
        bounding_box.y_max - bounding_box.y_min,
        bounding_box.z_max - bounding_box.z_min,
    ]
    block_sizes = [block_size.dx, block_size.dy, block_size.dz]

    n_blocks = Size3i(
        nx=max(1, math.ceil(extents[0] / block_sizes[0])),
        ny=max(1, math.ceil(extents[1] / block_sizes[1])),
        nz=max(1, math.ceil(extents[2] / block_sizes[2])),
    )
    origin = Point3(
        x=bounding_box.x_min,
        y=bounding_box.y_min,
        z=bounding_box.z_min,
    )
    actual_bbox = BoundingBox.from_origin_and_size(origin, n_blocks, block_size)
    return origin, n_blocks, actual_bbox


def _validate_bbox(bounding_box: BoundingBox) -> None:
    if (
        bounding_box.x_max <= bounding_box.x_min
        or bounding_box.y_max <= bounding_box.y_min
        or bounding_box.z_max <= bounding_box.z_min
    ):
        raise ValueError(
            "Extents must have max values greater than min values on all axes."
        )


def _local_design_result(
    object_name: str,
    object_path: str,
    description: str,
    bounding_box: BoundingBox,
    block_size: Size3d,
    coordinate_reference_system: str | None,
    size_unit_id: str | None,
    extent_source: str,
    source_summary: dict[str, str] | None = None,
) -> tuple[dict[str, Any], RegularBlockModelData]:
    _validate_bbox(bounding_box)
    origin, n_blocks, resulting_bbox = _derive_regular_grid_definition(
        bounding_box,
        block_size,
    )

    regular_block_model_data = RegularBlockModelData(
        name=object_name,
        description=description or None,
        coordinate_reference_system=coordinate_reference_system or None,
        size_unit_id=size_unit_id,
        origin=origin,
        n_blocks=n_blocks,
        block_size=block_size,
    )

    block_model_data = {
        "name": object_name,
        "description": description or None,
        "coordinate_reference_system": coordinate_reference_system or "unspecified",
        "size_unit_id": size_unit_id,
        "origin": {
            "x": origin.x,
            "y": origin.y,
            "z": origin.z,
        },
        "n_blocks": {
            "nx": n_blocks.nx,
            "ny": n_blocks.ny,
            "nz": n_blocks.nz,
        },
        "block_size": {
            "dx": block_size.dx,
            "dy": block_size.dy,
            "dz": block_size.dz,
        },
    }

    result: dict[str, Any] = {
        "status": "success",
        "extent_source": extent_source,
        "object_path": object_path,
        "requested_bounding_box": _bounding_box_to_dict(bounding_box),
        "derived_grid": {
            "origin": block_model_data["origin"],
            "n_blocks": block_model_data["n_blocks"],
            "block_size": block_model_data["block_size"],
            "resulting_bounding_box": _bounding_box_to_dict(resulting_bbox),
            "total_blocks": n_blocks.nx * n_blocks.ny * n_blocks.nz,
        },
        "message": "Block model designed.",
    }
    if source_summary is not None:
        result["source"] = source_summary
    return result, regular_block_model_data


def register_block_model_tools(mcp) -> None:
    """Register block-model-specific tools with the FastMCP server."""

    @mcp.tool()
    async def regular_block_model_design_from_extents(
        object_name: str,
        object_path: str,
        block_size_x: float,
        block_size_y: float,
        block_size_z: float,
        x_min: float,
        x_max: float,
        y_min: float,
        y_max: float,
        z_min: float,
        z_max: float,
        description: str = "",
        padding_x: float = 0.0,
        padding_y: float = 0.0,
        padding_z: float = 0.0,
        coordinate_reference_system: str = "unspecified",
        size_unit_id: str | None = None,
    ) -> dict[str, Any]:
        """Build a local regular block model definition from explicit extents."""
        if block_size_x <= 0 or block_size_y <= 0 or block_size_z <= 0:
            raise ValueError("block sizes must all be greater than zero.")

        bounding_box = BoundingBox(
            x_min=x_min - padding_x,
            x_max=x_max + padding_x,
            y_min=y_min - padding_y,
            y_max=y_max + padding_y,
            z_min=z_min - padding_z,
            z_max=z_max + padding_z,
        )
        block_size = Size3d(dx=block_size_x, dy=block_size_y, dz=block_size_z)
        result, typed_data = _local_design_result(
            object_name=object_name,
            object_path=object_path,
            description=description,
            bounding_box=bounding_box,
            block_size=block_size,
            coordinate_reference_system=normalize_crs(
                coordinate_reference_system, none_value=None
            ),
            size_unit_id=size_unit_id,
            extent_source="explicit_extents",
        )
        envelope = staging_service.stage_local_build(
            object_type="regular_block_model",
            typed_payload=typed_data,
        )
        n_blocks = typed_data.n_blocks
        object_registry.register(
            name=object_name,
            object_type="regular_block_model",
            stage_id=envelope.stage_id,
            summary={"total_blocks": n_blocks.nx * n_blocks.ny * n_blocks.nz},
        )
        return result

    @mcp.tool()
    async def block_model_get_definition_details(
        block_model_name: str | None = None,
    ) -> dict[str, Any]:
        """Inspect and summarize a block model definition by name."""
        try:
            entry, parsed = object_registry.get_payload(
                name=block_model_name, object_type="regular_block_model"
            )
        except (StageError, ResolutionError):
            try:
                entry, parsed = object_registry.get_payload(
                    name=block_model_name, object_type="block_model"
                )
            except (StageError, ResolutionError) as exc:
                raise ValueError(str(exc)) from exc

        if isinstance(parsed, BlockModelData):
            g = parsed.geometry
            bbox = BoundingBox.from_origin_and_size(
                g.origin,
                g.n_blocks,
                g.block_size,
            )
            result: dict[str, Any] = {
                "status": "success",
                "block_model_kind": "standard",
                "model_type": g.model_type,
                "name": parsed.name,
                "description": parsed.description,
                "coordinate_reference_system": parsed.coordinate_reference_system
                or "unspecified",
                "origin": {
                    "x": g.origin.x,
                    "y": g.origin.y,
                    "z": g.origin.z,
                },
                "n_blocks": {
                    "nx": g.n_blocks.nx,
                    "ny": g.n_blocks.ny,
                    "nz": g.n_blocks.nz,
                },
                "block_size": {
                    "dx": g.block_size.dx,
                    "dy": g.block_size.dy,
                    "dz": g.block_size.dz,
                },
                "total_blocks": (g.n_blocks.nx * g.n_blocks.ny * g.n_blocks.nz),
                "resulting_bounding_box": _bounding_box_to_dict(bbox),
                "attribute_names": [attr.name for attr in parsed.attributes],
            }
            return result

        # RegularBlockModelData
        bbox = BoundingBox.from_origin_and_size(
            parsed.origin,
            parsed.n_blocks,
            parsed.block_size,
        )
        return {
            "status": "success",
            "name": parsed.name,
            "description": parsed.description,
            "coordinate_reference_system": parsed.coordinate_reference_system
            or "unspecified",
            "size_unit_id": parsed.size_unit_id,
            "origin": {
                "x": parsed.origin.x,
                "y": parsed.origin.y,
                "z": parsed.origin.z,
            },
            "n_blocks": {
                "nx": parsed.n_blocks.nx,
                "ny": parsed.n_blocks.ny,
                "nz": parsed.n_blocks.nz,
            },
            "block_size": {
                "dx": parsed.block_size.dx,
                "dy": parsed.block_size.dy,
                "dz": parsed.block_size.dz,
            },
            "total_blocks": (
                parsed.n_blocks.nx * parsed.n_blocks.ny * parsed.n_blocks.nz
            ),
            "resulting_bounding_box": _bounding_box_to_dict(bbox),
        }
