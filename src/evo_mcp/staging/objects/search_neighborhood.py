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
  - get_summary: Return the neighborhood configuration.

Create:
  - staging_create_object("search_neighborhood", params): Stage from explicit ellipsoid ranges.
  - staging_invoke_interaction(variogram_name, "create_search_neighborhood", params): Derive from staged variogram.
"""

from collections.abc import Mapping
from typing import Any, Literal

from evo.compute.tasks.common import SearchNeighborhood as ComputeSearchNeighborhood
from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from evo_mcp.context import get_evo_context
from evo_mcp.staging.objects.base import (
    Interaction,
    StagedObjectType,
    staged_object_type_registry,
)

_UNIT_ELLIPSOID_RANGES = {"major": 1.0, "semi_major": 1.0, "minor": 1.0}


class SearchNeighborhoodLimits(BaseModel):
    """Shared sample, sector, and drillhole limits delegated to evo-compute's SearchNeighborhood."""

    max_samples: int = Field(..., ge=1, description="Maximum number of samples to use.")
    min_samples: int | None = Field(None, ge=1, description="Minimum number of samples required (optional).")
    max_empty_octants: int | None = Field(
        None,
        ge=0,
        le=8,
        description="Maximum number of empty octants allowed (0-8; omit or use 8 to disable).",
    )
    max_samples_per_octant: int | None = Field(
        None,
        ge=1,
        description="Maximum number of samples to use from each octant.",
    )
    max_empty_quadrants: int | None = Field(
        None,
        ge=0,
        le=4,
        description="Maximum number of empty quadrants allowed (0-4; omit or use 4 to disable).",
    )
    max_samples_per_quadrant: int | None = Field(
        None,
        ge=1,
        description="Maximum number of samples to use from each quadrant.",
    )
    max_samples_per_drillhole: int | None = Field(
        None,
        ge=1,
        description="Maximum number of samples per drillhole (requires a DownholeIntervals source).",
    )
    max_drillholes: int | None = Field(
        None,
        ge=1,
        validation_alias=AliasChoices("max_drillholes", "max_drillholes_per_estimate"),
        description="Maximum number of drillholes per estimate (requires a DownholeIntervals source).",
    )
    min_drillholes: int | None = Field(
        None,
        ge=0,
        validation_alias=AliasChoices("min_drillholes", "min_drillholes_per_estimate"),
        description="Minimum number of distinct drillholes per estimate (Kriging-only; requires a DownholeIntervals source).",
    )
    drillhole_limit_scope: Literal["global", "quadrant", "octant"] | None = Field(
        None,
        description="Scope at which max_samples_per_drillhole applies ('global', 'quadrant', or 'octant').",
    )

    @property
    def max_drillholes_per_estimate(self) -> int | None:
        """Backwards-compatible alias for `max_drillholes`."""
        return self.max_drillholes

    @model_validator(mode="before")
    @classmethod
    def _validate_drillhole_aliases(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        cleaned = dict(data)
        for canonical, legacy in (
            ("max_drillholes", "max_drillholes_per_estimate"),
            ("min_drillholes", "min_drillholes_per_estimate"),
        ):
            if canonical in cleaned and legacy in cleaned:
                if cleaned[canonical] != cleaned[legacy]:
                    ComputeSearchNeighborhood.model_validate(
                        {
                            "ellipsoid": {"ranges": _UNIT_ELLIPSOID_RANGES},
                            "max_samples": 1,
                            canonical: cleaned[canonical],
                            legacy: cleaned[legacy],
                        }
                    )
                cleaned.pop(legacy)
        return cleaned

    def _validate_with_compute_neighborhood(
        self,
        *,
        major: float = 1.0,
        semi_major: float = 1.0,
        minor: float = 1.0,
        dip_azimuth: float = 0.0,
        dip: float = 0.0,
        pitch: float = 0.0,
    ) -> ComputeSearchNeighborhood:
        return ComputeSearchNeighborhood(
            ellipsoid={
                "ranges": {"major": major, "semi_major": semi_major, "minor": minor},
                "rotation": {"dip_azimuth": dip_azimuth, "dip": dip, "pitch": pitch},
            },
            max_samples=self.max_samples,
            min_samples=self.min_samples,
            max_empty_octants=self.max_empty_octants,
            max_samples_per_octant=self.max_samples_per_octant,
            max_empty_quadrants=self.max_empty_quadrants,
            max_samples_per_quadrant=self.max_samples_per_quadrant,
            max_samples_per_drillhole=self.max_samples_per_drillhole,
            max_drillholes=self.max_drillholes,
            min_drillholes=self.min_drillholes,
            drillhole_limit_scope=self.drillhole_limit_scope,
        )

    def limit_kwargs(self) -> dict[str, Any]:
        """Return validated sample, sector, and drillhole limit fields as keyword arguments."""
        return {
            "max_samples": self.max_samples,
            "min_samples": self.min_samples,
            "max_empty_octants": self.max_empty_octants,
            "max_samples_per_octant": self.max_samples_per_octant,
            "max_empty_quadrants": self.max_empty_quadrants,
            "max_samples_per_quadrant": self.max_samples_per_quadrant,
            "max_samples_per_drillhole": self.max_samples_per_drillhole,
            "max_drillholes": self.max_drillholes,
            "min_drillholes": self.min_drillholes,
            "drillhole_limit_scope": self.drillhole_limit_scope,
        }


class SearchNeighborhoodData(SearchNeighborhoodLimits):
    """In-memory representation of a staged search neighborhood.

    Contains the parameters required to configure a search neighborhood for
    estimation workflows: ellipsoid ranges, rotation, and sample/sector/drillhole limits.
    """

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    name: str
    major: float = Field(gt=0)
    semi_major: float = Field(gt=0)
    minor: float = Field(gt=0)
    dip_azimuth: float = 0.0
    dip: float = 0.0
    pitch: float = 0.0

    def to_compute_neighborhood(self) -> ComputeSearchNeighborhood:
        """Convert to an `evo.compute.tasks.common.SearchNeighborhood` instance."""
        return self._validate_with_compute_neighborhood(
            major=self.major,
            semi_major=self.semi_major,
            minor=self.minor,
            dip_azimuth=self.dip_azimuth,
            dip=self.dip,
            pitch=self.pitch,
        )

    @model_validator(mode="after")
    def _validate_neighborhood(self) -> "SearchNeighborhoodData":
        self.to_compute_neighborhood()
        return self


# ── Interaction handlers ──────────────────────────────────────────────────────


# ── Create interaction handlers ────────────────────────────────────────────────


class CreateFromRangesParams(SearchNeighborhoodLimits):
    """Parameters for creating a search neighborhood from explicit ellipsoid ranges."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    object_name: str = Field(..., description="Name for the staged search neighborhood.")
    major: float = Field(..., gt=0, description="Major ellipsoid range.")
    semi_major: float = Field(..., gt=0, description="Semi-major ellipsoid range.")
    minor: float = Field(..., gt=0, description="Minor ellipsoid range.")
    dip_azimuth: float = Field(0.0, description="Dip azimuth in degrees.")
    dip: float = Field(0.0, description="Dip in degrees.")
    pitch: float = Field(0.0, description="Pitch in degrees.")

    @model_validator(mode="after")
    def check_samples(self) -> "CreateFromRangesParams":
        self._validate_with_compute_neighborhood(
            major=self.major,
            semi_major=self.semi_major,
            minor=self.minor,
            dip_azimuth=self.dip_azimuth,
            dip=self.dip,
            pitch=self.pitch,
        )
        return self


async def _create_from_ranges(params: CreateFromRangesParams) -> dict[str, Any]:
    """Design a search neighborhood from explicit ellipsoid ranges and stage it."""
    data = SearchNeighborhoodData(
        name=params.object_name,
        major=params.major,
        semi_major=params.semi_major,
        minor=params.minor,
        dip_azimuth=params.dip_azimuth,
        dip=params.dip,
        pitch=params.pitch,
        **params.limit_kwargs(),
    )
    ctx = await get_evo_context()
    envelope = ctx.object_staging.stage_local_build(
        object_type="search_neighborhood",
        typed_payload=data,
    )
    ctx.object_registry.register(
        name=params.object_name,
        object_type="search_neighborhood",
        stage_id=envelope.stage_id,
    )
    return {
        "name": params.object_name,
        "configuration": data.model_dump(),
        "message": "Search neighborhood created from explicit ranges.",
    }


# ── Object type definition ────────────────────────────────────────────────────


class SearchNeighborhoodObjectType(StagedObjectType):
    """Staged search neighborhood sub-model with validation and inspection."""

    object_type = "search_neighborhood"
    display_name = "Search Neighborhood"
    data_class = SearchNeighborhoodData

    def summarize(self, payload: SearchNeighborhoodData) -> dict[str, Any]:
        return {
            "name": payload.name,
            "configuration": payload.model_dump(),
            "message": "Search neighborhood summary.",
        }

    def __init__(self) -> None:
        super().__init__()

        async def _get_summary(p: SearchNeighborhoodData) -> dict[str, Any]:
            return self.summarize(p)

        self._register_interaction(
            Interaction(
                name="get_summary",
                display_name="Get Summary",
                description="Return the full neighborhood configuration (ellipsoid, samples, derivation).",
                handler=_get_summary,
            )
        )

    async def create(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        validated = CreateFromRangesParams.model_validate(params or {})
        return await _create_from_ranges(validated)


# Auto-register at import time.
staged_object_type_registry.register(SearchNeighborhoodObjectType())
