# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Input parameters and validation for compute tools."""

import math
from typing import Annotated, Any

from evo.compute.tasks.common import Filter, SearchNeighborhood
from evo.compute.tasks.geostatistics.idw import IDWParameters
from evo.compute.tasks.geostatistics.kriging import (
    BlockDiscretization,
    KrigingParameters,
    OrdinaryKriging,
    SimpleKriging,
)
from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, Field

from evo_mcp.utils.tool_support import VariogramObjectId


def _check_sample_limits(search: SearchNeighborhood) -> SearchNeighborhood:
    if search.max_samples < 1:
        raise ValueError("max_samples must be at least 1.")
    if search.min_samples is not None and not 1 <= search.min_samples <= search.max_samples:
        raise ValueError("min_samples must be between 1 and max_samples.")
    return search


def _canonical_search(search: Any) -> Any:
    """Map `rotation` to `_rotation`: the SDK Ellipsoid dataclass otherwise drops the rotation silently."""
    ellipsoid = search.get("ellipsoid") if isinstance(search, dict) else None
    if not isinstance(ellipsoid, dict) or "rotation" not in ellipsoid:
        return search
    if "_rotation" in ellipsoid:
        raise ValueError("Specify the search ellipsoid rotation once, as 'rotation'.")
    ellipsoid = dict(ellipsoid)
    ellipsoid["_rotation"] = ellipsoid.pop("rotation")
    return {**search, "ellipsoid": ellipsoid}


def _strict_validator(model: type[BaseModel]) -> BeforeValidator:
    """Reject unknown fields at every nesting level; most SDK compute models silently ignore them."""

    def validate(value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        value = {
            key: _canonical_search(item) if key in ("search", "neighborhood") else item for key, item in value.items()
        }
        return model.model_validate(value, extra="forbid")

    return BeforeValidator(validate)


def _validate_search(value: Any) -> Any:
    if not isinstance(value, dict):
        return value
    return SearchNeighborhood.model_validate(_canonical_search(value), extra="forbid")


SearchInput = Annotated[SearchNeighborhood, BeforeValidator(_validate_search), AfterValidator(_check_sample_limits)]
FilterInput = Annotated[Filter, _strict_validator(Filter)]


class KrigingBuildParams(BaseModel):
    """Parameters for building a validated kriging payload."""

    model_config = ConfigDict(extra="forbid")

    target_object_id: str = Field(
        description=(
            "UUID of the target object for an estimation or spatial-validation workflow. "
            "For kriging, this should identify an existing BlockModel or Regular3DGrid in the provided workspace."
        ),
    )
    target_attribute: str = Field(
        description="Target attribute name to create or update on the target object for estimation results.",
    )
    point_set_object_id: str = Field(
        description="UUID of the source PointSet object containing known sample values.",
    )
    point_set_attribute: str = Field(
        description="Existing numeric source attribute name on the point set object, for example 'CU_pct'.",
    )
    variogram_object_id: VariogramObjectId
    search: SearchInput = Field(
        description="Search neighborhood parameters including ellipsoid and sample counts.",
    )
    method: SimpleKriging | OrdinaryKriging = Field(
        default_factory=OrdinaryKriging,
        description="Kriging method object. Defaults to ordinary kriging.",
    )
    source_filter: FilterInput | None = Field(
        default=None,
        description=(
            "Optional filter restricting kriging to a subset of the source samples. "
            "Provide a Filter with a 'where' condition, e.g. "
            "{'where': {'type': 'condition', 'attribute': 'grade', 'operator': 'greater_than', 'threshold': 0.0}}."
        ),
    )
    target_filter: FilterInput | None = Field(
        default=None,
        description=(
            "Optional filter restricting kriging to a subset of the target object. "
            "Provide a Filter with a 'where' condition, e.g. "
            "{'where': {'type': 'condition', 'attribute': 'domain', 'operator': 'in', 'values': ['LMS1', 'LMS2']}}."
        ),
    )
    block_discretization: BlockDiscretization | None = Field(
        default=None,
        description="Optional sub-block discretization settings.",
    )


class NeighborhoodBuildParams(BaseModel):
    """Shared inputs for neighborhood-based estimation without a variogram."""

    model_config = ConfigDict(extra="forbid")

    target_object_id: str = Field(description="UUID of the existing target object in the workspace.")
    target_attribute: str = Field(description="Attribute to create or update with estimated values.")
    point_set_object_id: str = Field(description="UUID of the source PointSet containing known sample values.")
    point_set_attribute: str = Field(description="Existing numeric attribute containing the source sample values.")
    search: SearchInput = Field(description="Search ellipsoid, rotation, and sample limits.")
    source_filter: FilterInput | None = Field(default=None, description="Optional filter on source samples.")
    target_filter: FilterInput | None = Field(default=None, description="Optional filter on target locations.")


class IDWBuildParams(NeighborhoodBuildParams):
    """Inputs for inverse distance weighting estimation."""

    power: float = Field(
        default=2.0,
        gt=0,
        allow_inf_nan=False,
        description="Positive inverse-distance exponent in ellipsoid space; defaults to classic IDW power 2.",
    )


def _check_kriging_scenario(scenario: KrigingParameters) -> KrigingParameters:
    _check_sample_limits(scenario.search)
    return scenario


def _check_idw_scenario(scenario: IDWParameters) -> IDWParameters:
    if not math.isfinite(scenario.power):
        raise ValueError("power must be finite.")
    _check_sample_limits(scenario.neighborhood)
    return scenario


KrigingBuildInput = Annotated[KrigingBuildParams, _strict_validator(KrigingBuildParams)]
IDWBuildInput = Annotated[IDWBuildParams, _strict_validator(IDWBuildParams)]
KrigingScenario = Annotated[
    KrigingParameters, _strict_validator(KrigingParameters), AfterValidator(_check_kriging_scenario)
]
IDWScenario = Annotated[IDWParameters, _strict_validator(IDWParameters), AfterValidator(_check_idw_scenario)]
