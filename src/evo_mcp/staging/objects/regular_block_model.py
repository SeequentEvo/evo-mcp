# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Regular block model staged object type with discoverable interactions.

Supports ``RegularBlockModelData`` (locally designed regular grids).

Interactions:
  - get_definition_details: Inspect grid geometry, origin, block size, and bounding box.
"""

import math
from typing import Any

from evo.blockmodels.typed import RegularBlockModelData
from evo.common.typed import BoundingBox
from evo.objects.typed import BlockModel, Point3, Size3d, Size3i
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evo_mcp.staging.errors import StageValidationError
from evo_mcp.staging.helpers import (
    Point3Schema,
    Size3dSchema,
    Size3iSchema,
    _bbox_dict,
)
from evo_mcp.staging.objects.base import (
    EvoStagedObjectType,
    Interaction,
    staged_object_type_registry,
)
from evo_mcp.staging.runtime import get_registry, get_staging_service
from evo_mcp.utils.tool_support import resolve_crs


def _resolve_regular_block_model_crs(
    coordinate_reference_system: Any,
    *,
    none_value: Any = None,
) -> str | None:
    resolved = resolve_crs(coordinate_reference_system, none_value=none_value)
    if resolved == none_value:
        return none_value
    if isinstance(resolved, int):
        return f"EPSG:{resolved}"
    return resolved


def _details_from_regular(parsed: RegularBlockModelData) -> dict[str, Any]:
    bbox = BoundingBox.from_origin_and_size(parsed.origin, parsed.n_blocks, parsed.block_size)
    return {
        "status": "success",
        "name": parsed.name,
        "description": parsed.description,
        "coordinate_reference_system": parsed.coordinate_reference_system or "unspecified",
        "size_unit_id": parsed.size_unit_id,
        "origin": {"x": parsed.origin.x, "y": parsed.origin.y, "z": parsed.origin.z},
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
        "total_blocks": parsed.n_blocks.nx * parsed.n_blocks.ny * parsed.n_blocks.nz,
        "resulting_bounding_box": _bbox_dict(bbox),
    }


# ── Interaction handlers ──────────────────────────────────────────────────────


async def _get_definition_details(payload: Any) -> dict[str, Any]:
    return _details_from_regular(payload)


# ── Create interaction helpers ─────────────────────────────────────────────────


class RegularBlockModelCreateParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object_name: str = Field(..., description="Name for the block model.")
    object_path: str = Field("", description="Path for the new object (e.g. '/models/grid.json').")
    block_size_x: float = Field(..., gt=0, description="Block size in X direction.")
    block_size_y: float = Field(..., gt=0, description="Block size in Y direction.")
    block_size_z: float = Field(..., gt=0, description="Block size in Z direction.")
    x_min: float = Field(..., description="Minimum X extent.")
    x_max: float = Field(..., description="Maximum X extent.")
    y_min: float = Field(..., description="Minimum Y extent.")
    y_max: float = Field(..., description="Maximum Y extent.")
    z_min: float = Field(..., description="Minimum Z extent.")
    z_max: float = Field(..., description="Maximum Z extent.")
    padding_x: float = Field(0.0, ge=0, description="Extra padding added to X extents on each side.")
    padding_y: float = Field(0.0, ge=0, description="Extra padding added to Y extents on each side.")
    padding_z: float = Field(0.0, ge=0, description="Extra padding added to Z extents on each side.")
    description: str = Field("", description="Object description.")
    coordinate_reference_system: str | int = Field(
        "unspecified",
        description="CRS (unspecified, EPSG int, or EPSG-prefixed string).",
    )
    size_unit_id: str | None = Field(None, description="Size unit identifier.")

    @model_validator(mode="after")
    def check_extents(self) -> "RegularBlockModelCreateParams":
        padded_x_max = self.x_max + self.padding_x
        padded_x_min = self.x_min - self.padding_x
        padded_y_max = self.y_max + self.padding_y
        padded_y_min = self.y_min - self.padding_y
        padded_z_max = self.z_max + self.padding_z
        padded_z_min = self.z_min - self.padding_z
        if padded_x_max <= padded_x_min or padded_y_max <= padded_y_min or padded_z_max <= padded_z_min:
            raise ValueError("Extents must have max values greater than min values on all axes (after padding).")
        return self


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
    origin = Point3(x=bounding_box.x_min, y=bounding_box.y_min, z=bounding_box.z_min)
    actual_bbox = BoundingBox.from_origin_and_size(origin, n_blocks, block_size)
    return origin, n_blocks, actual_bbox


async def _create(params: RegularBlockModelCreateParams) -> dict[str, Any]:
    """Build a local regular block model definition from explicit extents."""
    bounding_box = BoundingBox(
        x_min=params.x_min - params.padding_x,
        x_max=params.x_max + params.padding_x,
        y_min=params.y_min - params.padding_y,
        y_max=params.y_max + params.padding_y,
        z_min=params.z_min - params.padding_z,
        z_max=params.z_max + params.padding_z,
    )

    block_size = Size3d(dx=params.block_size_x, dy=params.block_size_y, dz=params.block_size_z)
    origin, n_blocks, resulting_bbox = _derive_regular_grid_definition(bounding_box, block_size)

    resolved_crs = _resolve_regular_block_model_crs(
        params.coordinate_reference_system,
        none_value=None,
    )
    typed_data = RegularBlockModelData(
        name=params.object_name,
        description=params.description or None,
        coordinate_reference_system=resolved_crs,
        size_unit_id=params.size_unit_id,
        origin=origin,
        n_blocks=n_blocks,
        block_size=block_size,
    )

    envelope = get_staging_service().stage_local_build(
        object_type="regular_block_model",
        typed_payload=typed_data,
    )
    get_registry().register(
        name=params.object_name,
        object_type="regular_block_model",
        stage_id=envelope.stage_id,
        summary={"total_blocks": n_blocks.nx * n_blocks.ny * n_blocks.nz},
    )
    return {
        "status": "success",
        "extent_source": "explicit_extents",
        "object_path": params.object_path,
        "requested_bounding_box": _bbox_dict(bounding_box),
        "derived_grid": {
            "origin": {"x": origin.x, "y": origin.y, "z": origin.z},
            "n_blocks": {"nx": n_blocks.nx, "ny": n_blocks.ny, "nz": n_blocks.nz},
            "block_size": {
                "dx": block_size.dx,
                "dy": block_size.dy,
                "dz": block_size.dz,
            },
            "resulting_bounding_box": _bbox_dict(resulting_bbox),
            "total_blocks": n_blocks.nx * n_blocks.ny * n_blocks.nz,
        },
        "message": "Block model designed.",
    }


# ── Publish handler ───────────────────────────────────────────────────────────


# ── Object type definition ───────────────────────────────────────────────────


class RegularBlockModelObjectType(EvoStagedObjectType):
    """Staged locally-designed regular block model.

    Cannot be imported from Evo (``evo_class = None``) — locally created only.
    Published via ``mode='create'`` as a new BlockModel in Evo.
    """

    object_type = "regular_block_model"
    display_name = "Regular Block Model"
    evo_class = None
    data_class = RegularBlockModelData
    supported_publish_modes = frozenset({"create"})


    def summarize(self, payload: RegularBlockModelData) -> dict[str, Any]:
        n = payload.n_blocks
        b = payload.block_size
        total = n.nx * n.ny * n.nz
        attr_count = len(payload.cell_data.columns) if payload.cell_data is not None else 0
        return {
            "block_model_kind": "regular",
            "total_blocks": total,
            "nx": n.nx,
            "ny": n.ny,
            "nz": n.nz,
            "block_size_dx": b.dx,
            "block_size_dy": b.dy,
            "block_size_dz": b.dz,
            "attribute_count": attr_count,
            "coordinate_reference_system": payload.coordinate_reference_system,
        }

    def from_dict(self, data: dict[str, Any]) -> RegularBlockModelData:
        try:
            name = data["name"]
        except KeyError as exc:
            raise StageValidationError("RegularBlockModelData dict is missing required key 'name'.") from exc
        try:
            origin = Point3Schema.model_validate(data.get("origin", {})).to_sdk()
            n_blocks = Size3iSchema.model_validate(data.get("n_blocks", {})).to_sdk()
            block_size = Size3dSchema.model_validate(data.get("block_size", {})).to_sdk()
        except Exception as exc:
            raise StageValidationError(f"Regular block model geometry validation failed: {exc}") from exc

        resolved_crs = _resolve_regular_block_model_crs(
            data.get("coordinate_reference_system"),
            none_value=None,
        )

        return RegularBlockModelData(
            name=name,
            description=data.get("description"),
            coordinate_reference_system=resolved_crs,
            size_unit_id=data.get("size_unit_id"),
            origin=origin,
            n_blocks=n_blocks,
            block_size=block_size,
        )

    def __init__(self) -> None:
        super().__init__()
        self._register_interaction(
            Interaction(
                name="get_definition_details",
                display_name="Get Definition Details",
                description="Inspect grid geometry, origin, block size, bounding box, and attributes.",
                handler=_get_definition_details,
            )
        )

    async def create(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        validated = RegularBlockModelCreateParams.model_validate(params or {})
        return await _create(validated)

    async def publish_create(self, context, data, path):
        return await BlockModel.create_regular(context, data, path=path)


# Auto-register at import time.
staged_object_type_registry.register(RegularBlockModelObjectType())
