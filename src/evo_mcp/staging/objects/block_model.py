# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Subblocked block model staged object type with discoverable interactions.

Supports ``BlockModelData`` (imported/subblocked block models).

Interactions:
  - get_definition_details: Inspect grid geometry, origin, block size, and attributes.
"""

from __future__ import annotations

from typing import Any

from evo.common.typed import BoundingBox
from evo.objects.typed import (
    BlockModel,
    BlockModelData,
)

from evo_mcp.staging.helpers import _bbox_dict, _validate_grid_geometry
from evo_mcp.staging.objects.base import (
    Interaction,
    StagedObjectType,
    staged_object_type_registry,
)
from evo_mcp.utils.tool_support import extract_crs, format_crs, schema_label


def _details_from_block_model_data(parsed: BlockModelData) -> dict[str, Any]:
    g = parsed.geometry
    bbox = BoundingBox.from_origin_and_size(g.origin, g.n_blocks, g.block_size)
    return {
        "status": "success",
        "block_model_kind": "subblocked",
        "model_type": g.model_type,
        "name": parsed.name,
        "description": parsed.description,
        "coordinate_reference_system": parsed.coordinate_reference_system
        or "unspecified",
        "origin": {"x": g.origin.x, "y": g.origin.y, "z": g.origin.z},
        "n_blocks": {"nx": g.n_blocks.nx, "ny": g.n_blocks.ny, "nz": g.n_blocks.nz},
        "block_size": {
            "dx": g.block_size.dx,
            "dy": g.block_size.dy,
            "dz": g.block_size.dz,
        },
        "total_blocks": g.n_blocks.nx * g.n_blocks.ny * g.n_blocks.nz,
        "resulting_bounding_box": _bbox_dict(bbox),
        "attribute_names": [attr.name for attr in parsed.attributes],
    }


# ── Interaction handlers ──────────────────────────────────────────────────────


async def _get_definition_details(
    payload: Any, params: dict[str, Any]
) -> dict[str, Any]:
    return _details_from_block_model_data(payload)


# ── Import / publish handlers ─────────────────────────────────────────────────


async def _import_block_model(
    obj: Any, context: Any
) -> tuple[Any, dict[str, Any], str]:
    data = BlockModelData(
        name=obj.name,
        description=getattr(obj, "description", None),
        coordinate_reference_system=format_crs(extract_crs(obj)),
        block_model_uuid=obj.block_model_uuid,
        block_model_version_uuid=getattr(obj, "block_model_version_uuid", None),
        geometry=obj.geometry,
        attributes=list(obj.attributes),
    )
    extras: dict[str, Any] = {"schema_id": schema_label(obj)}
    is_regular = getattr(obj.geometry, "model_type", None) == "regular"
    message = (
        "Regular block model imported. Can be published as a new version "
        "with publish_object(mode='new_version')."
        if is_regular
        else "Block model imported as reference (read-only; only regular "
        "block models can be published)."
    )
    return data, extras, message


# ── Object type definition ───────────────────────────────────────────────────


class BlockModelObjectType(StagedObjectType):
    """Staged imported/subblocked block model."""

    object_type = "block_model"
    display_name = "Block Model"
    evo_class = BlockModel
    data_classes = (BlockModelData,)
    supported_publish_modes = frozenset({"new_version"})
    fixture_path_segment = "blockmodels"
    role_label = "Block model"
    role_article = "a BlockModel"
    create_params_model = None  # import-only; local creation not supported

    def _validate(self, payload: BlockModelData) -> None:
        g = payload.geometry
        _validate_grid_geometry(g.block_size, g.n_blocks, "BlockModelData")

    def summarize(self, payload: BlockModelData) -> dict[str, Any]:
        g = payload.geometry
        n = g.n_blocks
        b = g.block_size
        total = n.nx * n.ny * n.nz
        return {
            "block_model_kind": "subblocked",
            "model_type": g.model_type,
            "total_blocks": total,
            "nx": n.nx,
            "ny": n.ny,
            "nz": n.nz,
            "block_size_dx": b.dx,
            "block_size_dy": b.dy,
            "block_size_dz": b.dz,
            "attribute_count": len(payload.attributes),
            "attribute_names": [attr.name for attr in payload.attributes],
            "coordinate_reference_system": payload.coordinate_reference_system,
        }

    async def create(self, params: Any) -> dict[str, Any]:
        raise NotImplementedError(
            "BlockModel does not support local creation. "
            "Use stage_import_object to import an existing block model from Evo."
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

    async def import_handler(self, obj, context):
        return await _import_block_model(obj, context)

    async def publish_replace(self, context, url, data):
        return await BlockModel.replace(context, url, data)


# Auto-register.
staged_object_type_registry.register(BlockModelObjectType())
