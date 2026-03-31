# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Object-type codecs for staging.

Each codec handles one typed SDK data class:
  - PointSetCodec   -> PointSetData
  - VariogramCodec  -> VariogramData
  - BlockModelCodec -> RegularBlockModelData | BlockModelData

BlockModelCodec supports two block-model variants:
  - *regular* (``RegularBlockModelData``): locally-creatable regular grids.
  - *standard* (``BlockModelData``): non-regular models (sub-blocked, octree, …)
    imported from the Block Model Service.  Standard models are import-only.

Typed *data* classes are used, not service-backed wrapper classes.

Each codec also provides to_dict() / from_dict() for round-trip serialization.
Serialization/deserialization logic lives here, not in evo-python-sdk.
"""

from __future__ import annotations

import math
import uuid as _uuid
from typing import Any, Protocol, Union, runtime_checkable

import pandas as pd
from evo.blockmodels.typed import RegularBlockModelData
from evo.objects.typed import (
    BlockModelAttribute,
    BlockModelData,
    BlockModelGeometry,
    CubicStructure,
    Ellipsoid,
    EllipsoidRanges,
    ExponentialStructure,
    GaussianStructure,
    GeneralisedCauchyStructure,
    LinearStructure,
    PointSetData,
    Rotation,
    SphericalStructure,
    SpheroidalStructure,
    VariogramData,
)
from evo.objects.typed import Point3, Size3d, Size3i

from evo_mcp.staging.errors import StageValidationError

__all__ = [
    "Codec",
    "PointSetCodec",
    "VariogramCodec",
    "BlockModelCodec",
    "get_codec",
    "variogram_structure_from_dict",
]


@runtime_checkable
class Codec(Protocol):
    """Shared interface for all staging codecs."""

    object_type: str

    def to_stage_payload(self, *args: Any, **kwargs: Any) -> Any: ...
    def from_stage_payload(self, payload: Any) -> Any: ...
    def to_dict(self, data: Any) -> dict: ...
    def from_dict(self, data: dict) -> Any: ...
    def summarize(self, payload: Any) -> dict: ...
    def validate(self, payload: Any) -> None: ...


def _coerce_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise StageValidationError(f"{field_name} must be numeric; got {value!r}.") from exc


def _coerce_int(value: Any, field_name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise StageValidationError(f"{field_name} must be an integer; got {value!r}.") from exc


def _ellipsoid_from_dict(data: dict[str, Any]) -> Ellipsoid:
    """Build an Ellipsoid from a dict produced by Ellipsoid.to_dict()."""
    ranges_d = data.get("ellipsoid_ranges", {})
    rotation_d = data.get("rotation", {})
    return Ellipsoid(
        ranges=EllipsoidRanges(
            major=_coerce_float(ranges_d.get("major"), "ellipsoid_ranges.major"),
            semi_major=_coerce_float(ranges_d.get("semi_major"), "ellipsoid_ranges.semi_major"),
            minor=_coerce_float(ranges_d.get("minor"), "ellipsoid_ranges.minor"),
        ),
        rotation=Rotation(
            dip_azimuth=_coerce_float(rotation_d.get("dip_azimuth", 0.0), "rotation.dip_azimuth"),
            dip=_coerce_float(rotation_d.get("dip", 0.0), "rotation.dip"),
            pitch=_coerce_float(rotation_d.get("pitch", 0.0), "rotation.pitch"),
        ),
    )


_ALPHA_REQUIRED = {"spheroidal", "generalisedcauchy"}
_VALID_ALPHA = {3, 5, 7, 9}


def variogram_structure_from_dict(structure: dict[str, Any]) -> Any:
    """Deserialize a variogram structure dict into the appropriate typed SDK class.

    This is the canonical deserialization entry-point for variogram structures
    within evo-mcp. It mirrors the structure-building logic used by variogram
    tool helpers, kept here so codecs own the serialization boundary.
    """
    if not isinstance(structure, dict):
        raise StageValidationError(
            f"Variogram structure must be a dict, got {type(structure).__name__}."
        )
    variogram_type = structure.get("variogram_type")
    if not variogram_type:
        raise StageValidationError("Variogram structure dict is missing 'variogram_type'.")

    contribution = _coerce_float(structure.get("contribution"), "structure.contribution")
    anisotropy_payload = structure.get("anisotropy")
    if not isinstance(anisotropy_payload, dict):
        raise StageValidationError("Variogram structure dict is missing 'anisotropy'.")
    anisotropy = _ellipsoid_from_dict(anisotropy_payload)

    vtype = str(variogram_type).lower()
    alpha = structure.get("alpha")

    if vtype in _ALPHA_REQUIRED:
        if alpha is None:
            raise StageValidationError(f"alpha is required for {vtype} structures.")
        alpha = _coerce_int(alpha, "alpha")
        if alpha not in _VALID_ALPHA:
            raise StageValidationError(
                f"alpha must be one of {sorted(_VALID_ALPHA)} for {vtype} structures."
            )
    elif alpha is not None:
        raise StageValidationError(
            f"alpha is only valid for spheroidal/generalisedcauchy structures, not {vtype}."
        )

    if vtype == "spherical":
        return SphericalStructure(contribution=contribution, anisotropy=anisotropy)
    if vtype == "exponential":
        return ExponentialStructure(contribution=contribution, anisotropy=anisotropy)
    if vtype == "gaussian":
        return GaussianStructure(contribution=contribution, anisotropy=anisotropy)
    if vtype == "cubic":
        return CubicStructure(contribution=contribution, anisotropy=anisotropy)
    if vtype == "linear":
        return LinearStructure(contribution=contribution, anisotropy=anisotropy)
    if vtype == "spheroidal":
        return SpheroidalStructure(contribution=contribution, anisotropy=anisotropy, alpha=alpha)
    if vtype == "generalisedcauchy":
        return GeneralisedCauchyStructure(contribution=contribution, anisotropy=anisotropy, alpha=alpha)
    raise StageValidationError(f"Unsupported variogram_type: {variogram_type!r}.")


class PointSetCodec:
    """Codec for PointSetData staged payloads."""

    object_type: str = "point_set"

    def to_stage_payload(self, typed_object: PointSetData) -> PointSetData:
        if not isinstance(typed_object, PointSetData):
            raise StageValidationError(
                f"Expected PointSetData, got {type(typed_object).__name__}."
            )
        return typed_object

    def from_stage_payload(self, payload: PointSetData) -> PointSetData:
        if not isinstance(payload, PointSetData):
            raise StageValidationError(
                f"Expected PointSetData in store, got {type(payload).__name__}."
            )
        return payload

    def to_dict(self, payload: PointSetData) -> dict[str, Any]:
        """Serialize PointSetData to a JSON-compatible dict (round-trips via from_dict)."""
        df = payload.locations
        attributes: dict[str, Any] = {}
        for column in df.columns:
            if column in {"x", "y", "z"}:
                continue
            values = df[column]
            if pd.api.types.is_numeric_dtype(values):
                attributes[column] = [None if (isinstance(v, float) and math.isnan(v)) else v for v in values.tolist()]
            else:
                attributes[column] = values.fillna("").astype(str).tolist()
        return {
            "name": payload.name,
            "description": payload.description,
            "tags": payload.tags,
            "coordinate_reference_system": payload.coordinate_reference_system,
            "data": {
                "coordinates": {
                    "x": [None if (isinstance(v, float) and math.isnan(v)) else v for v in df["x"].astype(float).tolist()],
                    "y": [None if (isinstance(v, float) and math.isnan(v)) else v for v in df["y"].astype(float).tolist()],
                    "z": [None if (isinstance(v, float) and math.isnan(v)) else v for v in df["z"].astype(float).tolist()],
                },
                "attributes": attributes,
            },
        }

    def from_dict(self, data: dict[str, Any]) -> PointSetData:
        """Reconstruct PointSetData from a dict produced by to_dict()."""
        raw = data.get("data", {})
        coords = raw.get("coordinates", {})
        try:
            df = pd.DataFrame(
                {
                    "x": pd.to_numeric(pd.Series(coords["x"]), errors="raise").astype("float64"),
                    "y": pd.to_numeric(pd.Series(coords["y"]), errors="raise").astype("float64"),
                    "z": pd.to_numeric(pd.Series(coords["z"]), errors="raise").astype("float64"),
                }
            )
        except KeyError as exc:
            raise StageValidationError(
                f"PointSetData dict is missing required coordinate key: {exc}"
            ) from exc
        for attr_name, attr_values in (raw.get("attributes") or {}).items():
            df[attr_name] = pd.Series(attr_values)
        try:
            name = data["name"]
        except KeyError as exc:
            raise StageValidationError(
                "PointSetData dict is missing required key 'name'."
            ) from exc
        return PointSetData(
            name=name,
            description=data.get("description"),
            tags=data.get("tags") or {},
            coordinate_reference_system=data.get("coordinate_reference_system"),
            locations=df,
        )

    def summarize(self, payload: PointSetData) -> dict[str, Any]:
        df = payload.locations
        attribute_names = [c for c in df.columns if c not in {"x", "y", "z"}]
        return {
            "point_count": int(len(df)),
            "attribute_count": len(attribute_names),
            "attribute_names": attribute_names,
            "coordinate_reference_system": payload.coordinate_reference_system,
        }

    def validate(self, payload: PointSetData) -> None:
        if not isinstance(payload, PointSetData):
            raise StageValidationError(
                f"Expected PointSetData, got {type(payload).__name__}."
            )
        df = payload.locations
        if df is None or len(df) == 0:
            raise StageValidationError("PointSetData locations must be non-empty.")
        for col in ("x", "y", "z"):
            if col not in df.columns:
                raise StageValidationError(
                    f"PointSetData locations must contain column '{col}'."
                )


class VariogramCodec:
    """Codec for VariogramData staged payloads."""

    object_type: str = "variogram"

    def to_stage_payload(self, typed_object: VariogramData) -> VariogramData:
        if not isinstance(typed_object, VariogramData):
            raise StageValidationError(
                f"Expected VariogramData, got {type(typed_object).__name__}."
            )
        return typed_object

    def from_stage_payload(self, payload: VariogramData) -> VariogramData:
        if not isinstance(payload, VariogramData):
            raise StageValidationError(
                f"Expected VariogramData in store, got {type(payload).__name__}."
            )
        return payload

    def to_dict(self, payload: VariogramData) -> dict[str, Any]:
        """Serialize VariogramData to a JSON-compatible dict (round-trips via from_dict)."""
        return {
            "name": payload.name,
            "description": payload.description,
            "tags": payload.tags,
            "extensions": payload.extensions,
            "sill": float(payload.sill),
            "nugget": float(payload.nugget),
            "is_rotation_fixed": payload.is_rotation_fixed,
            "structures": payload.get_structures_as_dicts(),
            "data_variance": float(payload.data_variance) if payload.data_variance is not None else None,
            "modelling_space": payload.modelling_space,
            "domain": payload.domain,
            "attribute": payload.attribute,
        }

    def from_dict(self, data: dict[str, Any]) -> VariogramData:
        """Reconstruct VariogramData from a dict produced by to_dict()."""
        structures_raw = data.get("structures")
        if not isinstance(structures_raw, list):
            raise StageValidationError("VariogramData dict is missing 'structures'.")
        structures = [variogram_structure_from_dict(s) for s in structures_raw]

        sill_raw = data.get("sill")
        if sill_raw is None:
            raise StageValidationError("VariogramData dict is missing 'sill'.")

        try:
            name = data["name"]
        except KeyError as exc:
            raise StageValidationError(
                "VariogramData dict is missing required key 'name'."
            ) from exc
        return VariogramData(
            name=name,
            description=data.get("description"),
            tags=data.get("tags") or {},
            extensions=data.get("extensions"),
            sill=_coerce_float(sill_raw, "sill"),
            nugget=_coerce_float(data.get("nugget", 0.0), "nugget"),
            is_rotation_fixed=bool(data.get("is_rotation_fixed", False)),
            structures=structures,
            data_variance=(
                _coerce_float(data["data_variance"], "data_variance")
                if data.get("data_variance") is not None
                else None
            ),
            modelling_space=data.get("modelling_space"),
            domain=data.get("domain"),
            attribute=data.get("attribute"),
        )

    def summarize(self, payload: VariogramData) -> dict[str, Any]:
        structures = payload.get_structures_as_dicts()
        structure_types = [s.get("variogram_type") for s in structures]
        return {
            "structure_count": len(structures),
            "sill": payload.sill,
            "nugget": payload.nugget,
            "structure_types": structure_types,
            "modelling_space": payload.modelling_space,
        }

    def validate(self, payload: VariogramData) -> None:
        if not isinstance(payload, VariogramData):
            raise StageValidationError(
                f"Expected VariogramData, got {type(payload).__name__}."
            )
        if not payload.structures:
            raise StageValidationError(
                "VariogramData must have at least one structure."
            )
        if payload.sill <= 0:
            raise StageValidationError("VariogramData sill must be greater than zero.")


AnyBlockModelData = Union[RegularBlockModelData, BlockModelData]


def _rotation_to_dict(rotation: Rotation | None) -> dict[str, float] | None:
    if rotation is None:
        return None
    return {
        "dip_azimuth": float(rotation.dip_azimuth),
        "dip": float(rotation.dip),
        "pitch": float(rotation.pitch),
    }


def _rotation_from_dict(data: dict[str, Any] | None) -> Rotation | None:
    if data is None:
        return None
    return Rotation(
        dip_azimuth=_coerce_float(data.get("dip_azimuth", 0.0), "rotation.dip_azimuth"),
        dip=_coerce_float(data.get("dip", 0.0), "rotation.dip"),
        pitch=_coerce_float(data.get("pitch", 0.0), "rotation.pitch"),
    )


class BlockModelCodec:
    """Codec for RegularBlockModelData and BlockModelData staged payloads."""

    object_type: str = "block_model"

    def to_stage_payload(
        self, typed_object: AnyBlockModelData
    ) -> AnyBlockModelData:
        if not isinstance(typed_object, (RegularBlockModelData, BlockModelData)):
            raise StageValidationError(
                f"Expected RegularBlockModelData or BlockModelData, got {type(typed_object).__name__}."
            )
        return typed_object

    def from_stage_payload(
        self, payload: AnyBlockModelData
    ) -> AnyBlockModelData:
        if not isinstance(payload, (RegularBlockModelData, BlockModelData)):
            raise StageValidationError(
                f"Expected RegularBlockModelData or BlockModelData in store, got {type(payload).__name__}."
            )
        return payload

    def to_dict(self, payload: AnyBlockModelData) -> dict[str, Any]:
        """Serialize RegularBlockModelData or BlockModelData to a JSON-compatible dict."""
        if isinstance(payload, BlockModelData):
            g = payload.geometry
            return {
                "block_model_kind": "standard",
                "name": payload.name,
                "description": payload.description,
                "tags": payload.tags,
                "extensions": payload.extensions,
                "coordinate_reference_system": payload.coordinate_reference_system,
                "block_model_uuid": str(payload.block_model_uuid),
                "block_model_version_uuid": (
                    str(payload.block_model_version_uuid)
                    if payload.block_model_version_uuid is not None
                    else None
                ),
                "model_type": g.model_type,
                "origin": {"x": float(g.origin.x), "y": float(g.origin.y), "z": float(g.origin.z)},
                "n_blocks": {"nx": int(g.n_blocks.nx), "ny": int(g.n_blocks.ny), "nz": int(g.n_blocks.nz)},
                "block_size": {"dx": float(g.block_size.dx), "dy": float(g.block_size.dy), "dz": float(g.block_size.dz)},
                "rotation": _rotation_to_dict(g.rotation),
                "attributes": [
                    {
                        "name": attr.name,
                        "attribute_type": attr.attribute_type,
                        "block_model_column_uuid": (
                            str(attr.block_model_column_uuid)
                            if attr.block_model_column_uuid is not None
                            else None
                        ),
                        "unit": attr.unit,
                    }
                    for attr in payload.attributes
                ],
            }
        # Regular block model
        o = payload.origin
        n = payload.n_blocks
        b = payload.block_size
        return {
            "block_model_kind": "regular",
            "name": payload.name,
            "description": payload.description,
            "coordinate_reference_system": payload.coordinate_reference_system,
            "size_unit_id": getattr(payload, "size_unit_id", None),
            "origin": {"x": float(o.x), "y": float(o.y), "z": float(o.z)},
            "n_blocks": {"nx": int(n.nx), "ny": int(n.ny), "nz": int(n.nz)},
            "block_size": {"dx": float(b.dx), "dy": float(b.dy), "dz": float(b.dz)},
        }

    def from_dict(self, data: dict[str, Any]) -> AnyBlockModelData:
        """Reconstruct RegularBlockModelData or BlockModelData from a dict produced by to_dict()."""
        kind = data.get("block_model_kind", "regular")

        try:
            name = data["name"]
        except KeyError as exc:
            raise StageValidationError(
                "Block model dict is missing required key 'name'."
            ) from exc

        origin_d = data.get("origin", {})
        n_d = data.get("n_blocks", {})
        b_d = data.get("block_size", {})

        origin = Point3(
            x=_coerce_float(origin_d.get("x"), "origin.x"),
            y=_coerce_float(origin_d.get("y"), "origin.y"),
            z=_coerce_float(origin_d.get("z"), "origin.z"),
        )
        n_blocks = Size3i(
            nx=_coerce_int(n_d.get("nx"), "n_blocks.nx"),
            ny=_coerce_int(n_d.get("ny"), "n_blocks.ny"),
            nz=_coerce_int(n_d.get("nz"), "n_blocks.nz"),
        )
        block_size = Size3d(
            dx=_coerce_float(b_d.get("dx"), "block_size.dx"),
            dy=_coerce_float(b_d.get("dy"), "block_size.dy"),
            dz=_coerce_float(b_d.get("dz"), "block_size.dz"),
        )

        if kind == "standard":
            bm_uuid_raw = data.get("block_model_uuid")
            if not bm_uuid_raw:
                raise StageValidationError(
                    "Standard BlockModelData dict is missing 'block_model_uuid'."
                )
            bm_version_raw = data.get("block_model_version_uuid")
            attrs_raw = data.get("attributes", [])
            attributes = [
                BlockModelAttribute(
                    name=a["name"],
                    attribute_type=a.get("attribute_type", "unknown"),
                    block_model_column_uuid=(
                        _uuid.UUID(a["block_model_column_uuid"])
                        if a.get("block_model_column_uuid")
                        else None
                    ),
                    unit=a.get("unit"),
                )
                for a in attrs_raw
            ]
            return BlockModelData(
                name=name,
                description=data.get("description"),
                tags=data.get("tags") or {},
                extensions=data.get("extensions"),
                coordinate_reference_system=data.get("coordinate_reference_system"),
                block_model_uuid=_uuid.UUID(str(bm_uuid_raw)),
                block_model_version_uuid=(
                    _uuid.UUID(str(bm_version_raw)) if bm_version_raw is not None else None
                ),
                geometry=BlockModelGeometry(
                    model_type=data.get("model_type", "unknown"),
                    origin=origin,
                    n_blocks=n_blocks,
                    block_size=block_size,
                    rotation=_rotation_from_dict(data.get("rotation")),
                ),
                attributes=attributes,
            )

        # Default: regular
        return RegularBlockModelData(
            name=name,
            description=data.get("description"),
            coordinate_reference_system=data.get("coordinate_reference_system"),
            size_unit_id=data.get("size_unit_id"),
            origin=origin,
            n_blocks=n_blocks,
            block_size=block_size,
        )

    def summarize(self, payload: AnyBlockModelData) -> dict[str, Any]:
        if isinstance(payload, BlockModelData):
            g = payload.geometry
            n = g.n_blocks
            b = g.block_size
            total = n.nx * n.ny * n.nz
            return {
                "block_model_kind": "standard",
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
        # Regular
        n = payload.n_blocks
        b = payload.block_size
        total = n.nx * n.ny * n.nz
        attr_count = (
            len(payload.cell_data.columns) if payload.cell_data is not None else 0
        )
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

    def validate(self, payload: AnyBlockModelData) -> None:
        if isinstance(payload, BlockModelData):
            g = payload.geometry
            b = g.block_size
            if b.dx <= 0 or b.dy <= 0 or b.dz <= 0:
                raise StageValidationError(
                    "BlockModelData block sizes must all be greater than zero."
                )
            n = g.n_blocks
            if n.nx < 1 or n.ny < 1 or n.nz < 1:
                raise StageValidationError(
                    "BlockModelData n_blocks must all be >= 1."
                )
            return

        if not isinstance(payload, RegularBlockModelData):
            raise StageValidationError(
                f"Expected RegularBlockModelData or BlockModelData, got {type(payload).__name__}."
            )
        b = payload.block_size
        if b.dx <= 0 or b.dy <= 0 or b.dz <= 0:
            raise StageValidationError(
                "RegularBlockModelData block sizes must all be greater than zero."
            )
        n = payload.n_blocks
        if n.nx < 1 or n.ny < 1 or n.nz < 1:
            raise StageValidationError(
                "RegularBlockModelData n_blocks must all be >= 1."
            )


_POINT_SET_CODEC = PointSetCodec()
_VARIOGRAM_CODEC = VariogramCodec()
_BLOCK_MODEL_CODEC = BlockModelCodec()


def get_codec(object_type: str) -> Codec:
    """Return the codec for a given object_type string."""
    if object_type == "point_set":
        return _POINT_SET_CODEC
    if object_type == "variogram":
        return _VARIOGRAM_CODEC
    if object_type == "block_model":
        return _BLOCK_MODEL_CODEC
    raise StageValidationError(f"Unknown object_type: {object_type!r}")
