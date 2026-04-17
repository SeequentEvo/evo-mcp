# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Search neighborhood staged sub-model with discoverable interactions.

A search neighborhood is a derived sub-model that can be staged and
inspected like any other object. It captures ellipsoid geometry, rotation,
and sample-limit parameters used in estimation workflows.

Unlike primary object types (variogram, point_set, block_model), a search
neighborhood is a lightweight derived artifact — typically built from a
variogram's anisotropy structure.

Interactions:
  - summarize: Return the neighborhood configuration.
  - validate: Check parameter consistency and range validity.
"""

from typing import Any, Literal

from evo.compute.tasks.common import SearchNeighborhood as ComputeSearchNeighborhood
from evo.objects.typed import (
    Ellipsoid,
    EllipsoidRanges,
    Rotation,
    Variogram,
    object_from_uuid,
)
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evo_mcp.staging.objects.base import (
    Interaction,
    StagedObjectType,
    staged_object_type_registry,
)
from evo_mcp.staging.objects.variogram import _select_structure
from evo_mcp.staging.runtime import get_registry
from evo_mcp.utils.tool_support import (
    get_workspace_context,
    require_object_role,
)


class SearchNeighborhoodData(BaseModel):
    """In-memory representation of a staged search neighborhood.

    This is a local data model — not an Evo SDK type. It captures the
    parameters needed to configure a search neighborhood for kriging or
    other estimation workflows.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    max_samples: int = Field(ge=1)
    min_samples: int | None = Field(None, ge=0)
    major: float = Field(0.0, gt=0)
    semi_major: float = Field(0.0, gt=0)
    minor: float = Field(0.0, gt=0)
    dip_azimuth: float = 0.0
    dip: float = 0.0
    pitch: float = 0.0
    derivation_mode: str = "user-specified"
    source_variogram_name: str | None = None
    scale_factor: float = 1.0
    description: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "max_samples": self.max_samples,
            "min_samples": self.min_samples,
            "ellipsoid": {
                "ranges": {
                    "major": self.major,
                    "semi_major": self.semi_major,
                    "minor": self.minor,
                },
                "rotation": {
                    "dip_azimuth": self.dip_azimuth,
                    "dip": self.dip,
                    "pitch": self.pitch,
                },
            },
            "derivation": {
                "mode": self.derivation_mode,
                "source_variogram_name": self.source_variogram_name,
                "scale_factor": self.scale_factor,
            },
        }


# ── Interaction handlers ──────────────────────────────────────────────────────


async def _summarize(payload: SearchNeighborhoodData, params: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": payload.name,
        "configuration": payload.to_dict(),
        "message": "Search neighborhood summary.",
    }


async def _validate(payload: SearchNeighborhoodData, params: dict[str, Any]) -> dict[str, Any]:
    issues: list[str] = []

    if payload.min_samples is not None and payload.min_samples > payload.max_samples:
        issues.append("min_samples cannot exceed max_samples.")
    if payload.major < payload.semi_major:
        issues.append("major range should be >= semi_major range.")
    if payload.semi_major < payload.minor:
        issues.append("semi_major range should be >= minor range.")

    return {
        "name": payload.name,
        "is_valid": len(issues) == 0,
        "issues": issues,
        "message": "No issues found." if not issues else f"{len(issues)} issue(s) detected.",
    }


# ── Create interaction handler ─────────────────────────────────────────────────


class SearchNeighborhoodCreateParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    max_samples: int = Field(..., ge=1, description="Maximum number of samples to use.")
    min_samples: int | None = Field(None, ge=0, description="Minimum number of samples (optional).")
    major: float | None = Field(None, gt=0, description="Major ellipsoid range.")
    semi_major: float | None = Field(None, gt=0, description="Semi-major ellipsoid range.")
    minor: float | None = Field(None, gt=0, description="Minor ellipsoid range.")
    dip_azimuth: float | None = Field(None, description="Dip azimuth in degrees (optional override).")
    dip: float | None = Field(None, description="Dip in degrees (optional override).")
    pitch: float | None = Field(None, description="Pitch in degrees (optional override).")
    variogram_name: str | None = Field(None, description="Name of a staged variogram to derive ranges from.")
    variogram_object_id: str | None = Field(None, description="UUID of a variogram object in Evo.")
    workspace_id: str | None = Field(
        None, description="Workspace UUID (required when variogram_object_id is provided)."
    )
    structure_index: int | None = Field(None, ge=0, description="Variogram structure index to use.")
    selection_mode: Literal["first", "largest_major"] = Field("first", description="Structure selection strategy.")
    scale_factor: float = Field(1.0, gt=0, description="Scale factor applied to variogram ranges.")
    preset: Literal["custom", "tight", "moderate", "broad"] = Field(
        "custom", description="Preset scale factor: tight=1.0, moderate=2.0, broad=3.0, custom=scale_factor."
    )

    @model_validator(mode="after")
    def check_inputs(self) -> "SearchNeighborhoodCreateParams":
        explicit = [self.major, self.semi_major, self.minor]
        has_any = any(v is not None for v in explicit)
        has_all = all(v is not None for v in explicit)
        if has_any and not has_all:
            raise ValueError("When specifying explicit ranges, all of major, semi_major, and minor must be provided.")
        if self.variogram_object_id is not None and self.variogram_name is not None:
            raise ValueError("Provide either variogram_object_id or variogram_name, not both.")
        if self.min_samples is not None and self.min_samples > self.max_samples:
            raise ValueError("min_samples cannot exceed max_samples.")
        return self


def _resolve_scale_factor(preset: str, scale_factor: float) -> float:
    if preset == "tight":
        return 1.0
    if preset == "moderate":
        return 2.0
    if preset == "broad":
        return 3.0
    return scale_factor


async def _create(params: SearchNeighborhoodCreateParams) -> dict[str, Any]:
    """Design a canonical search neighborhood for estimation workflows."""
    has_explicit_ranges = params.major is not None  # validator ensures all-or-none
    derivation_mode = "user-specified"
    derivation_details: dict[str, Any] = {
        "preset": params.preset,
        "scale_factor": params.scale_factor,
        "variogram_object_id": params.variogram_object_id,
    }

    if has_explicit_ranges:
        base_ranges = EllipsoidRanges(major=params.major, semi_major=params.semi_major, minor=params.minor)
        base_rotation = Rotation(
            dip_azimuth=params.dip_azimuth or 0.0,
            dip=params.dip or 0.0,
            pitch=params.pitch or 0.0,
        )
    elif params.variogram_name is not None:
        try:
            _, variogram_data = get_registry().get_payload(name=params.variogram_name, object_type="variogram")
        except Exception as exc:
            raise ValueError(str(exc)) from exc
        resolved_sf = _resolve_scale_factor(params.preset, params.scale_factor)
        structures = variogram_data.get_structures_as_dicts()
        if not structures:
            raise ValueError("No variogram structures available to select from.")
        sel_idx, sel_struct, sel_by = _select_structure(
            structures,
            params.structure_index,
            params.selection_mode,
        )

        ranges_d = sel_struct.get("anisotropy", {}).get("ellipsoid_ranges", {})
        maj = float(ranges_d.get("major"))
        smaj = float(ranges_d.get("semi_major"))
        mnr = float(ranges_d.get("minor"))
        if min(maj, smaj, mnr) <= 0:
            raise ValueError("Staged variogram selected structure must have positive ranges.")
        rot_d = sel_struct.get("anisotropy", {}).get("rotation", {})
        base_ranges = EllipsoidRanges(major=maj * resolved_sf, semi_major=smaj * resolved_sf, minor=mnr * resolved_sf)
        base_rotation = Rotation(
            dip_azimuth=float(rot_d.get("dip_azimuth", 0.0)),
            dip=float(rot_d.get("dip", 0.0)),
            pitch=float(rot_d.get("pitch", 0.0)),
        )
        derivation_mode = "variogram-scaled"
        derivation_details.update(
            {
                "variogram_object_id": None,
                "variogram_name": params.variogram_name,
                "selected_structure_index": sel_idx,
                "selected_by": sel_by,
                "selection_mode": params.selection_mode,
                "scale_factor": resolved_sf,
            }
        )
    else:
        if params.variogram_object_id is None:
            raise ValueError("Provide either explicit ranges, a variogram_name, or a variogram_object_id.")
        if params.workspace_id is None:
            raise ValueError("workspace_id is required when variogram_object_id is provided.")
        context = await get_workspace_context(params.workspace_id)
        try:
            variogram_object = await object_from_uuid(context, params.variogram_object_id)
        except Exception as exc:
            raise ValueError("Could not resolve the variogram object for neighborhood design.") from exc
        require_object_role(variogram_object, Variogram, "Variogram", "a Variogram")
        resolved_sf = _resolve_scale_factor(params.preset, params.scale_factor)
        base_ellipsoid = variogram_object.get_ellipsoid().scaled(resolved_sf)
        base_ranges = base_ellipsoid.ranges
        base_rotation = base_ellipsoid.rotation
        derivation_mode = "variogram-object-scaled"
        derivation_details["scale_factor"] = resolved_sf

    neighborhood_rotation = Rotation(
        dip_azimuth=params.dip_azimuth if params.dip_azimuth is not None else base_rotation.dip_azimuth,
        dip=params.dip if params.dip is not None else base_rotation.dip,
        pitch=params.pitch if params.pitch is not None else base_rotation.pitch,
    )
    neighborhood = ComputeSearchNeighborhood(
        ellipsoid=Ellipsoid(
            ranges=EllipsoidRanges(major=base_ranges.major, semi_major=base_ranges.semi_major, minor=base_ranges.minor),
            rotation=neighborhood_rotation,
        ),
        max_samples=params.max_samples,
        min_samples=params.min_samples,
    )
    return {
        "neighborhood": neighborhood.model_dump(mode="json", exclude_none=True),
        "derivation": {"mode": derivation_mode, **derivation_details},
        "message": "Search neighborhood designed using canonical ellipsoid and sample-limit fields.",
    }


# ── Object type definition ────────────────────────────────────────────────────


class SearchNeighborhoodObjectType(StagedObjectType):
    """Staged search neighborhood sub-model with validation and inspection."""

    object_type = "search_neighborhood"
    display_name = "Search Neighborhood"
    create_params_model = SearchNeighborhoodCreateParams

    def _validate(self, payload: SearchNeighborhoodData) -> None:
        pass  # Pydantic model handles field validation at construction time

    def summarize(self, payload: SearchNeighborhoodData) -> dict[str, Any]:
        return {
            "max_samples": payload.max_samples,
            "min_samples": payload.min_samples,
            "major": payload.major,
            "semi_major": payload.semi_major,
            "minor": payload.minor,
            "derivation_mode": payload.derivation_mode,
        }

    async def create(self, params: SearchNeighborhoodCreateParams) -> dict[str, Any]:
        return await _create(params)

    def __init__(self) -> None:
        super().__init__()
        self._register_interaction(
            Interaction(
                name="get_summary",
                display_name="Get Summary",
                description="Return the full neighborhood configuration (ellipsoid, samples, derivation).",
                handler=_summarize,
            )
        )
        self._register_interaction(
            Interaction(
                name="get_validation_report",
                display_name="Get Validation Report",
                description="Check parameter consistency: sample limits, range ordering, positive ranges.",
                handler=_validate,
            )
        )


# Auto-register at import time.
staged_object_type_registry.register(SearchNeighborhoodObjectType())
