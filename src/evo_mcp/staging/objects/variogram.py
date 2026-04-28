# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Variogram staged object type with discoverable interactions.

Interactions:
  - summarize: Return summary statistics.
  - get_structure_details: Inspect a selected structure.
  - get_ellipsoid_details: Return ellipsoid details with optional 3D points.
"""

import math
from typing import Any, Literal

from evo.objects.typed import (
    CubicStructure,
    Ellipsoid,
    EllipsoidRanges,
    ExponentialStructure,
    GaussianStructure,
    GeneralisedCauchyStructure,
    LinearStructure,
    Rotation,
    SphericalStructure,
    SpheroidalStructure,
    Variogram,
    VariogramData,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evo_mcp.staging.errors import StageValidationError
from evo_mcp.staging.helpers import RotationSchema
from evo_mcp.staging.objects.base import (
    EvoStagedObjectType,
    Interaction,
    staged_object_type_registry,
)
from evo_mcp.staging.runtime import get_registry, get_staging_service

# ── Variogram-specific helpers ────────────────────────────────────────────────


_ALPHA_REQUIRED = {"spheroidal", "generalisedcauchy"}
_VALID_ALPHA = {3, 5, 7, 9}


class EllipsoidRangesInput(BaseModel):
    """Validated user input for ellipsoid ranges (all must be positive)."""

    model_config = ConfigDict(extra="ignore")
    major: float = Field(..., gt=0)
    semi_major: float = Field(..., gt=0)
    minor: float = Field(..., gt=0)


class AnisotropyInput(BaseModel):
    """Validated user input for anisotropy (ranges + optional rotation)."""

    model_config = ConfigDict(extra="ignore")
    ellipsoid_ranges: EllipsoidRangesInput
    rotation: RotationSchema = Field(default_factory=RotationSchema)


class VariogramStructureInput(BaseModel):
    """Validated user input for a single variogram structure."""

    model_config = ConfigDict(extra="ignore")
    variogram_type: str
    contribution: float = Field(..., gt=0)
    anisotropy: AnisotropyInput
    alpha: int | None = None

    @model_validator(mode="after")
    def _validate_alpha(self) -> "VariogramStructureInput":
        vtype = self.variogram_type.lower()
        if vtype in _ALPHA_REQUIRED:
            if self.alpha is None:
                raise ValueError(f"alpha is required for {vtype} structures.")
            if self.alpha not in _VALID_ALPHA:
                raise ValueError(f"alpha must be one of {sorted(_VALID_ALPHA)} for {vtype} structures.")
        elif self.alpha is not None:
            raise ValueError(f"alpha is only valid for spheroidal/generalisedcauchy structures, not {vtype}.")
        return self

    def to_sdk(self) -> Any:
        """Convert to the appropriate SDK variogram structure object."""
        ellipsoid = Ellipsoid(
            ranges=EllipsoidRanges(
                major=self.anisotropy.ellipsoid_ranges.major,
                semi_major=self.anisotropy.ellipsoid_ranges.semi_major,
                minor=self.anisotropy.ellipsoid_ranges.minor,
            ),
            rotation=self.anisotropy.rotation.to_sdk(),
        )
        return _variogram_structure_from_inputs(self.variogram_type.lower(), self.contribution, ellipsoid, self.alpha)


def variogram_structure_from_dict(structure: dict[str, Any]) -> Any:
    """Deserialize a variogram structure dict into the appropriate typed SDK class."""
    if not isinstance(structure, dict):
        raise StageValidationError(f"Variogram structure must be a dict, got {type(structure).__name__}.")
    try:
        return VariogramStructureInput.model_validate(structure).to_sdk()
    except Exception as exc:
        raise StageValidationError(str(exc)) from exc


def _select_structure(
    structures: list[dict[str, Any]],
    structure_index: int | None,
    selection_mode: str,
) -> tuple[int, dict[str, Any], str]:
    """Select a variogram structure by index or selection mode.

    Returns (selected_index, structure_dict, selection_method).
    """
    if not structures:
        raise ValueError("Variogram must contain at least one structure.")
    if structure_index is not None:
        if structure_index < 0 or structure_index >= len(structures):
            raise ValueError(f"structure_index {structure_index} is out of range for {len(structures)} structure(s).")
        return structure_index, structures[structure_index], "structure_index"
    if selection_mode == "largest_major":
        idx = max(
            range(len(structures)),
            key=lambda i: float(structures[i].get("anisotropy", {}).get("ellipsoid_ranges", {}).get("major", 0.0)),
        )
        return idx, structures[idx], "largest_major"
    return 0, structures[0], "first"


# ── Interaction parameter models ──────────────────────────────────────────────


class VariogramCreateParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object_name: str = Field(..., description="Name for the new variogram.")
    sill: float = Field(
        ...,
        gt=0,
        description="Total sill (nugget + sum of all structure contributions).",
    )
    structures: list[VariogramStructureInput] = Field(
        ...,
        min_length=1,
        description="List of variogram structure objects.",
    )
    nugget: float = Field(0.0, ge=0.0, description="Nugget variance.")
    is_rotation_fixed: bool = Field(True, description="Whether rotation is fixed across all structures.")
    modelling_space: Literal["data", "normalscore"] = Field("data", description="Modelling space.")
    data_variance: float | None = Field(None, description="Data variance (defaults to sill if omitted).")
    attribute: str | None = Field(None, description="Attribute name the variogram describes.")
    domain: str | None = Field(None, description="Domain name.")
    description: str | None = Field(None, description="Object description.")
    tags: dict[str, Any] | None = Field(None, description="Tags dict.")
    extensions: dict[str, Any] | None = Field(None, description="Extensions dict.")


class StructureSelectionParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    structure_index: int | None = Field(
        None,
        ge=0,
        description="Zero-based index of the structure to select. When omitted, selection_mode is used.",
    )
    selection_mode: Literal["first", "largest_major"] = Field(
        "first",
        description="Auto-selection strategy when structure_index is not provided.",
    )


class GetEllipsoidDetailsParams(StructureSelectionParams):
    center_x: float = Field(0.0, description="Ellipsoid center X coordinate.")
    center_y: float = Field(0.0, description="Ellipsoid center Y coordinate.")
    center_z: float = Field(0.0, description="Ellipsoid center Z coordinate.")
    include_surface_points: bool = Field(True, description="Include surface mesh points for 3D plotting.")
    include_wireframe_points: bool = Field(True, description="Include wireframe points for 3D plotting.")


def _structure_payload(structure: dict[str, Any], index: int) -> dict[str, Any]:
    anisotropy = structure.get("anisotropy", {})
    ranges = anisotropy.get("ellipsoid_ranges", {})
    rotation = anisotropy.get("rotation", {})
    major = float(ranges.get("major", 0.0))
    semi_major = float(ranges.get("semi_major", 0.0))
    minor = float(ranges.get("minor", 0.0))
    dip_azimuth = float(rotation.get("dip_azimuth", 0.0))
    dip_val = float(rotation.get("dip", 0.0))
    pitch = float(rotation.get("pitch", 0.0))
    return {
        "structure_index": index,
        "structure_type": structure.get("variogram_type"),
        "contribution": float(structure.get("contribution", 0.0)),
        "alpha": structure.get("alpha"),
        "ranges": {"major": major, "semi_major": semi_major, "minor": minor},
        "rotation": {"dip_azimuth": dip_azimuth, "dip": dip_val, "pitch": pitch},
        "is_valid_for_ellipsoid": min(major, semi_major, minor) > 0,
        "has_rotation": any(abs(v) > 0 for v in [dip_azimuth, dip_val, pitch]),
    }


# ── Interaction handlers ──────────────────────────────────────────────────────


async def _summarize(payload: VariogramData) -> dict[str, Any]:
    structures = payload.get_structures_as_dicts()
    return {
        "name": payload.name,
        "sill": payload.sill,
        "nugget": payload.nugget,
        "structure_count": len(structures),
        "modelling_space": payload.modelling_space,
        "is_rotation_fixed": payload.is_rotation_fixed,
        "data_variance": payload.data_variance,
        "attribute": payload.attribute,
        "domain": payload.domain,
        "structure_types": [s.get("variogram_type") for s in structures],
    }


async def _get_structure_details(payload: VariogramData, params: StructureSelectionParams) -> dict[str, Any]:
    structures = payload.get_structures_as_dicts()
    idx, selected, selected_by = _select_structure(
        structures,
        params.structure_index,
        params.selection_mode,
    )
    return {
        "variogram_name": payload.name,
        "structure_count": len(structures),
        "selected_structure_index": idx,
        "selected_by": selected_by,
        "selection_mode": params.selection_mode,
        "structure": _structure_payload(selected, idx),
    }


async def _get_ellipsoid_details(payload: VariogramData, params: GetEllipsoidDetailsParams) -> dict[str, Any]:
    structures = payload.get_structures_as_dicts()
    idx, selected, selected_by = _select_structure(
        structures,
        params.structure_index,
        params.selection_mode,
    )
    details = _structure_payload(selected, idx)

    result: dict[str, Any] = {
        "variogram_name": payload.name,
        "structure_count": len(structures),
        "selected_structure_index": idx,
        "selected_by": selected_by,
        "selection_mode": params.selection_mode,
        "center": {"x": params.center_x, "y": params.center_y, "z": params.center_z},
        "ranges": details["ranges"],
        "rotation": details["rotation"],
        "is_valid_for_ellipsoid": details["is_valid_for_ellipsoid"],
        "visualization_note": (
            "Use surface_points with plotly Mesh3d(alphahull=0, opacity=0.3) and "
            "wireframe_points with plotly Scatter3d(mode='lines')."
        ),
    }
    if not params.include_surface_points and not params.include_wireframe_points:
        return result
    if not details["is_valid_for_ellipsoid"]:
        raise ValueError("Cannot generate ellipsoid points: selected structure has non-positive ranges.")
    ranges = details["ranges"]
    rotation = details["rotation"]
    ellipsoid = Ellipsoid(
        ranges=EllipsoidRanges(
            major=ranges["major"],
            semi_major=ranges["semi_major"],
            minor=ranges["minor"],
        ),
        rotation=Rotation(
            dip_azimuth=rotation["dip_azimuth"],
            dip=rotation["dip"],
            pitch=rotation["pitch"],
        ),
    )
    center = (params.center_x, params.center_y, params.center_z)
    if params.include_surface_points:
        sx, sy, sz = ellipsoid.surface_points(center=center)
        result["surface_points"] = {
            "x": sx.tolist(),
            "y": sy.tolist(),
            "z": sz.tolist(),
        }
    if params.include_wireframe_points:
        wx, wy, wz = ellipsoid.wireframe_points(center=center)
        result["wireframe_points"] = {
            "x": wx.tolist(),
            "y": wy.tolist(),
            "z": wz.tolist(),
        }
    return result

# ── Create interaction helpers ─────────────────────────────────────────────────


def _variogram_structure_from_inputs(
    structure_type: str,
    contribution: float,
    ellipsoid: Ellipsoid,
    alpha: int | None = None,
) -> Any:
    structure_type_lower = structure_type.lower()
    if structure_type_lower == "spherical":
        return SphericalStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "exponential":
        return ExponentialStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "gaussian":
        return GaussianStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "cubic":
        return CubicStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "linear":
        return LinearStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "spheroidal":
        return SpheroidalStructure(contribution=contribution, anisotropy=ellipsoid, alpha=alpha)
    if structure_type_lower == "generalisedcauchy":
        return GeneralisedCauchyStructure(contribution=contribution, anisotropy=ellipsoid, alpha=alpha)
    raise ValueError(
        "Unsupported structure_type. Use spherical, exponential, gaussian, cubic, linear, spheroidal, or generalisedcauchy."
    )


def _build_variogram_structures(
    structures_payload: list[VariogramStructureInput],
) -> list[Any]:
    if len(structures_payload) == 0:
        raise ValueError("structures must contain at least one structure.")
    return [s.to_sdk() for s in structures_payload]


# ── Create interaction helpers ─────────────────────────────────────────────────


class CreateSearchNeighborhoodParams(BaseModel):
    """Parameters for deriving a search neighborhood from a staged variogram."""

    model_config = ConfigDict(extra="ignore")

    object_name: str = Field(..., description="Name for the new staged search neighborhood.")
    max_samples: int = Field(..., ge=1, description="Maximum number of samples to use in kriging.")
    min_samples: int | None = Field(None, ge=0, description="Minimum number of samples (optional).")
    structure_index: int | None = Field(None, ge=0, description="Zero-based structure index. Uses selection_mode if omitted.")
    selection_mode: Literal["first", "largest_major"] = Field("first", description="Auto-selection strategy.")
    scale_factor: float = Field(1.0, gt=0, description="Multiplier applied to all ellipsoid ranges.")
    dip_azimuth: float | None = Field(None, description="Override dip azimuth in degrees.")
    dip: float | None = Field(None, description="Override dip in degrees.")
    pitch: float | None = Field(None, description="Override pitch in degrees.")

    @model_validator(mode="after")
    def check_samples(self) -> "CreateSearchNeighborhoodParams":
        if self.min_samples is not None and self.min_samples > self.max_samples:
            raise ValueError("min_samples cannot exceed max_samples.")
        return self


async def _create_search_neighborhood(payload: VariogramData, params: CreateSearchNeighborhoodParams) -> dict[str, Any]:
    """Derive a search neighborhood from this variogram and stage it."""
    from evo_mcp.staging.objects.search_neighborhood import SearchNeighborhoodData  # lazy — avoids circular import

    structures = payload.get_structures_as_dicts()
    if not structures:
        raise ValueError("Variogram must contain at least one structure.")

    sel_idx, sel_struct, sel_by = _select_structure(structures, params.structure_index, params.selection_mode)
    ranges_d = sel_struct.get("anisotropy", {}).get("ellipsoid_ranges", {})
    rot_d = sel_struct.get("anisotropy", {}).get("rotation", {})

    maj = float(ranges_d.get("major", 0.0)) * params.scale_factor
    smaj = float(ranges_d.get("semi_major", 0.0)) * params.scale_factor
    mnr = float(ranges_d.get("minor", 0.0)) * params.scale_factor
    if min(maj, smaj, mnr) <= 0:
        raise ValueError("Selected variogram structure must have positive ranges.")

    data = SearchNeighborhoodData(
        name=params.object_name,
        max_samples=params.max_samples,
        min_samples=params.min_samples,
        major=maj,
        semi_major=smaj,
        minor=mnr,
        dip_azimuth=params.dip_azimuth if params.dip_azimuth is not None else float(rot_d.get("dip_azimuth", 0.0)),
        dip=params.dip if params.dip is not None else float(rot_d.get("dip", 0.0)),
        pitch=params.pitch if params.pitch is not None else float(rot_d.get("pitch", 0.0)),
    )
    envelope = get_staging_service().stage_local_build(object_type="search_neighborhood", typed_payload=data)
    get_registry().register(
        name=params.object_name,
        object_type="search_neighborhood",
        stage_id=envelope.stage_id,
        summary=envelope.summary,
    )
    return {
        "name": params.object_name,
        "configuration": data.to_dict(),
        "derivation": {
            "variogram_name": payload.name,
            "selected_structure_index": sel_idx,
            "selected_by": sel_by,
            "selection_mode": params.selection_mode,
            "scale_factor": params.scale_factor,
        },
        "message": "Search neighborhood derived from variogram.",
    }


async def _create(params: VariogramCreateParams) -> dict[str, Any]:
    """Create a new variogram from canonical modelling parameters."""
    parsed_structures = _build_variogram_structures(params.structures)
    total_contribution = sum(s.contribution for s in parsed_structures)
    if not math.isclose(params.sill, params.nugget + total_contribution, rel_tol=1e-6, abs_tol=1e-6):
        raise ValueError("sill must equal nugget + the sum of all structure contributions.")

    variogram_data = VariogramData(
        name=params.object_name,
        description=params.description,
        tags=params.tags,
        extensions=params.extensions,
        sill=params.sill,
        nugget=params.nugget,
        is_rotation_fixed=params.is_rotation_fixed,
        modelling_space=params.modelling_space,
        data_variance=params.data_variance if params.data_variance is not None else params.sill,
        structures=parsed_structures,
        attribute=params.attribute,
        domain=params.domain,
    )

    envelope = get_staging_service().stage_local_build(
        object_type="variogram",
        typed_payload=variogram_data,
    )
    get_registry().register(
        name=params.object_name,
        object_type="variogram",
        stage_id=envelope.stage_id,
        summary=envelope.summary,
    )
    return {
        "name": params.object_name,
        "sill": params.sill,
        "nugget": params.nugget,
        "structure_count": len(params.structures),
        "message": "Variogram created.",
    }


# ── Import / publish handlers ─────────────────────────────────────────────────


async def _import_variogram(obj: Any, context: Any) -> tuple[Any, dict[str, Any], str]:
    data = VariogramData(
        name=obj.name,
        description=getattr(obj, "description", None) or None,
        sill=obj.sill,
        is_rotation_fixed=obj.is_rotation_fixed,
        structures=obj.structures,
        nugget=obj.nugget,
        data_variance=obj.data_variance,
        modelling_space=obj.modelling_space,
        domain=obj.domain,
        attribute=obj.attribute,
    )
    return data, {}, "Variogram imported."


# ── Object type definition ────────────────────────────────────────────────────


class VariogramObjectType(EvoStagedObjectType):
    """Staged variogram with inspection, search-param extraction, curve, and create interactions."""

    object_type = "variogram"
    display_name = "Variogram"
    evo_class = Variogram
    data_class = VariogramData
    supported_publish_modes = frozenset({"create", "new_version"})


    def _validate(self, payload: VariogramData) -> None:
        if not payload.structures:
            raise StageValidationError("VariogramData must have at least one structure.")
        if payload.sill <= 0:
            raise StageValidationError("VariogramData sill must be greater than zero.")

    def summarize(self, payload: VariogramData) -> dict[str, Any]:
        structures = payload.get_structures_as_dicts()
        return {
            "structure_count": len(structures),
            "sill": payload.sill,
            "nugget": payload.nugget,
            "structure_types": [s.get("variogram_type") for s in structures],
            "modelling_space": payload.modelling_space,
        }

    def from_dict(self, data: dict[str, Any]) -> VariogramData:
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
            raise StageValidationError("VariogramData dict is missing required key 'name'.") from exc
        return VariogramData(
            name=name,
            description=data.get("description"),
            tags=data.get("tags") or {},
            extensions=data.get("extensions"),
            sill=float(sill_raw),
            nugget=float(data.get("nugget", 0.0)),
            is_rotation_fixed=bool(data.get("is_rotation_fixed", False)),
            structures=structures,
            data_variance=(float(data["data_variance"]) if data.get("data_variance") is not None else None),
            modelling_space=data.get("modelling_space"),
            domain=data.get("domain"),
            attribute=data.get("attribute"),
        )

    def __init__(self) -> None:
        super().__init__()
        self._register_interaction(
            Interaction(
                name="get_summary",
                display_name="Get Summary",
                description="Return summary statistics for the variogram (sill, nugget, structures).",
                handler=_summarize,
            )
        )
        self._register_interaction(
            Interaction(
                name="get_structure_details",
                display_name="Get Structure Details",
                description="Inspect a selected variogram structure's ranges, rotation, and contribution.",
                handler=_get_structure_details,
                params_model=StructureSelectionParams,
            )
        )
        self._register_interaction(
            Interaction(
                name="get_ellipsoid_details",
                display_name="Get Ellipsoid Details",
                description="Return ellipsoid details with optional 3D surface/wireframe plotting points.",
                handler=_get_ellipsoid_details,
                params_model=GetEllipsoidDetailsParams,
            )
        )
        self._register_interaction(
            Interaction(
                name="create_search_neighborhood",
                display_name="Create Search Neighborhood",
                description=(
                    "Derive a search neighborhood from this variogram's anisotropy structure "
                    "and stage it as a new search_neighborhood object."
                ),
                handler=_create_search_neighborhood,
                params_model=CreateSearchNeighborhoodParams,
            )
        )

    async def create(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        validated = VariogramCreateParams.model_validate(params or {})
        return await _create(validated)

    async def import_handler(self, obj, context):
        return await _import_variogram(obj, context)

    async def publish_create(self, context, data, path):
        return await Variogram.create(context, data, path=path)

    async def publish_replace(self, context, url, data):
        return await Variogram.replace(context, url, data)


# Auto-register at import time.
staged_object_type_registry.register(VariogramObjectType())
