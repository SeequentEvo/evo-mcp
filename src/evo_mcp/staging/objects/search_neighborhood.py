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

from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from evo_mcp.staging.objects.base import (
    Interaction,
    StagedObjectType,
    staged_object_type_registry,
)
from evo_mcp.staging.runtime import get_registry, get_staging_service


class SearchNeighborhoodData(BaseModel):
    """In-memory representation of a staged search neighborhood.

    Contains exactly the parameters required to configure a search neighborhood
    for kriging: ellipsoid ranges, rotation, and sample limits.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    max_samples: int = Field(ge=1)
    min_samples: int | None = Field(None, ge=0)
    major: float = Field(gt=0)
    semi_major: float = Field(gt=0)
    minor: float = Field(gt=0)
    dip_azimuth: float = 0.0
    dip: float = 0.0
    pitch: float = 0.0

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
        }


# ── Interaction handlers ──────────────────────────────────────────────────────


async def _summarize(payload: SearchNeighborhoodData) -> dict[str, Any]:
    return {
        "name": payload.name,
        "configuration": payload.to_dict(),
        "message": "Search neighborhood summary.",
    }


# ── Create interaction handlers ────────────────────────────────────────────────


class CreateFromRangesParams(BaseModel):
    """Parameters for creating a search neighborhood from explicit ellipsoid ranges."""

    model_config = ConfigDict(extra="ignore")

    object_name: str = Field(..., description="Name for the staged search neighborhood.")
    max_samples: int = Field(..., ge=1, description="Maximum number of samples to use.")
    min_samples: int | None = Field(None, ge=0, description="Minimum number of samples (optional).")
    major: float = Field(..., gt=0, description="Major ellipsoid range.")
    semi_major: float = Field(..., gt=0, description="Semi-major ellipsoid range.")
    minor: float = Field(..., gt=0, description="Minor ellipsoid range.")
    dip_azimuth: float = Field(0.0, description="Dip azimuth in degrees.")
    dip: float = Field(0.0, description="Dip in degrees.")
    pitch: float = Field(0.0, description="Pitch in degrees.")

    @model_validator(mode="after")
    def check_samples(self) -> "CreateFromRangesParams":
        if self.min_samples is not None and self.min_samples > self.max_samples:
            raise ValueError("min_samples cannot exceed max_samples.")
        return self


async def _create_from_ranges(params: CreateFromRangesParams) -> dict[str, Any]:
    """Design a search neighborhood from explicit ellipsoid ranges and stage it."""
    data = SearchNeighborhoodData(
        name=params.object_name,
        max_samples=params.max_samples,
        min_samples=params.min_samples,
        major=params.major,
        semi_major=params.semi_major,
        minor=params.minor,
        dip_azimuth=params.dip_azimuth,
        dip=params.dip,
        pitch=params.pitch,
    )
    envelope = get_staging_service().stage_local_build(
        object_type="search_neighborhood",
        typed_payload=data,
    )
    get_registry().register(
        name=params.object_name,
        object_type="search_neighborhood",
        stage_id=envelope.stage_id,
    )
    return {
        "name": params.object_name,
        "configuration": data.to_dict(),
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
            "max_samples": payload.max_samples,
            "min_samples": payload.min_samples,
            "major": payload.major,
            "semi_major": payload.semi_major,
            "minor": payload.minor,
        }

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

    async def create(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        validated = CreateFromRangesParams.model_validate(params or {})
        return await _create_from_ranges(validated)


# Auto-register at import time.
staged_object_type_registry.register(SearchNeighborhoodObjectType())
