# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Input parameters and validation for compute tools."""

import math
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Annotated, Any

from evo.compute.tasks.common import Filter, SearchNeighborhood
from evo.compute.tasks.geostatistics.idw import IDWParameters
from evo.compute.tasks.geostatistics.kriging import (
    BlockDiscretization,
    KrigingParameters,
    OrdinaryKriging,
    SimpleKriging,
)
from pydantic import (
    AfterValidator,
    AliasChoices,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    GetJsonSchemaHandler,
    TypeAdapter,
    model_validator,
)
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from evo_mcp.utils.tool_support import VariogramObjectId

_KRIGING_METHOD_ADAPTER: TypeAdapter[SimpleKriging | OrdinaryKriging] = TypeAdapter(SimpleKriging | OrdinaryKriging)


def _clean_search_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    """Deduplicate identical drillhole aliases before strict SearchNeighborhood validation."""
    cleaned = dict(value)
    for canonical, legacy in (
        ("max_drillholes", "max_drillholes_per_estimate"),
        ("min_drillholes", "min_drillholes_per_estimate"),
    ):
        if canonical in cleaned and legacy in cleaned and cleaned[canonical] == cleaned[legacy]:
            cleaned.pop(legacy)
    return cleaned


def _validate_search(value: Any) -> Any:
    if isinstance(value, Mapping):
        return SearchNeighborhood.model_validate(_clean_search_mapping(value), extra="forbid")
    return value


def _validate_kriging_method(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _KRIGING_METHOD_ADAPTER.validate_python(value, extra="forbid")
    return value


def _strict_model_validator(model: type[BaseModel]) -> Callable[[Any], Any]:
    """Reject unknown fields at every nesting level; most SDK compute models silently ignore them."""

    def _validate(value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value
        cleaned = {
            key: _clean_search_mapping(item)
            if key in ("search", "neighborhood") and isinstance(item, Mapping)
            else item
            for key, item in value.items()
        }
        return model.model_validate(cleaned, extra="forbid")

    return _validate


def _resolve_neighborhood_aliases(data: Any) -> Any:
    """Reject conflicting `neighborhood`/`search` aliases and normalize identical ones."""
    if not isinstance(data, Mapping):
        return data
    cleaned = dict(data)
    if "neighborhood" in cleaned and "search" in cleaned:
        left, right = cleaned["neighborhood"], cleaned["search"]
        if isinstance(left, (Mapping, SearchNeighborhood)) and isinstance(right, (Mapping, SearchNeighborhood)):
            left_sn = _validate_search(left)
            right_sn = _validate_search(right)
            if left_sn.model_dump(mode="json") != right_sn.model_dump(mode="json"):
                raise ValueError("Conflicting values for 'neighborhood' and 'search'.")
            cleaned["neighborhood"] = left_sn
            cleaned.pop("search")
        else:
            raise ValueError("Conflicting values for 'neighborhood' and 'search'.")

    for key in ("neighborhood", "search"):
        if key in cleaned and isinstance(cleaned[key], Mapping):
            cleaned[key] = _clean_search_mapping(cleaned[key])

    return cleaned


def _resolve_kriging_aliases(data: Any) -> Any:
    """Reject conflicting canonical/legacy alias pairs and normalize identical ones."""
    cleaned = _resolve_neighborhood_aliases(data)
    if not isinstance(cleaned, dict):
        return cleaned

    if "kriging_method" in cleaned and "method" in cleaned:
        left, right = cleaned["kriging_method"], cleaned["method"]
        if isinstance(left, (Mapping, SimpleKriging, OrdinaryKriging)) and isinstance(
            right, (Mapping, SimpleKriging, OrdinaryKriging)
        ):
            left_method = _validate_kriging_method(left)
            right_method = _validate_kriging_method(right)
            if left_method.model_dump(mode="json") != right_method.model_dump(mode="json"):
                raise ValueError("Conflicting values for 'kriging_method' and 'method'.")
            cleaned["kriging_method"] = left_method
            cleaned.pop("method")
        else:
            raise ValueError("Conflicting values for 'kriging_method' and 'method'.")

    return cleaned


def _validate_kriging_scenario(value: Any) -> Any:
    if isinstance(value, Mapping):
        return KrigingParameters.model_validate(_resolve_kriging_aliases(value), extra="forbid")
    return value


class _AcceptEllipsoidAliasesSchema:
    """Allow `ranges` and optional `rotation` in validation JSON schemas while keeping canonical serialization."""

    def __get_pydantic_json_schema__(self, core_schema: CoreSchema, handler: GetJsonSchemaHandler) -> JsonSchemaValue:
        json_schema = handler(core_schema)
        if handler.mode != "validation":
            return json_schema
        resolved = handler.resolve_ref_schema(json_schema)
        self._patch_neighborhood_schema(resolved, handler)
        return json_schema

    @classmethod
    def _patch_neighborhood_schema(cls, schema: dict[str, Any], handler: GetJsonSchemaHandler) -> None:
        props = schema.get("properties")
        if not isinstance(props, dict):
            return
        if "ellipsoid" in props:
            ellipsoid = deepcopy(handler.resolve_ref_schema(props["ellipsoid"]))
            ellipsoid_props = ellipsoid.get("properties")
            if (
                isinstance(ellipsoid_props, dict)
                and "ellipsoid_ranges" in ellipsoid_props
                and "ranges" not in ellipsoid_props
            ):
                ranges_schema = deepcopy(ellipsoid_props["ellipsoid_ranges"])
                ranges_schema["title"] = "Ranges"
                ellipsoid_props["ranges"] = ranges_schema
                ellipsoid.pop("required", None)
                ellipsoid["anyOf"] = [
                    {"required": ["ellipsoid_ranges"]},
                    {"required": ["ranges"]},
                ]
                props["ellipsoid"] = ellipsoid
        for key in ("neighborhood", "search"):
            if key in props:
                neighborhood_schema = handler.resolve_ref_schema(props[key])
                cls._patch_neighborhood_schema(neighborhood_schema, handler)


SearchInput = Annotated[
    SearchNeighborhood,
    BeforeValidator(_validate_search),
    _AcceptEllipsoidAliasesSchema(),
]
KrigingMethodInput = Annotated[SimpleKriging | OrdinaryKriging, BeforeValidator(_validate_kriging_method)]
FilterInput = Annotated[Filter, BeforeValidator(_strict_model_validator(Filter))]
BlockDiscretizationInput = Annotated[BlockDiscretization, BeforeValidator(_strict_model_validator(BlockDiscretization))]


class KrigingBuildParams(BaseModel):
    """Parameters for building a validated kriging payload."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

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
        description=(
            "UUID of the source object containing known sample values "
            "(for example a PointSet or DownholeIntervals; drillhole neighborhood limits require DownholeIntervals)."
        ),
    )
    point_set_attribute: str = Field(
        description="Existing numeric source attribute name on the source object, for example 'CU_pct'.",
    )
    variogram_object_id: VariogramObjectId
    neighborhood: SearchInput = Field(
        validation_alias=AliasChoices("neighborhood", "search"),
        description=(
            "Search neighborhood parameters including ellipsoid, sample counts, "
            "and optional octant/quadrant/drillhole limits. Also accepts the legacy 'search' alias."
        ),
    )
    kriging_method: KrigingMethodInput = Field(
        default_factory=OrdinaryKriging,
        validation_alias=AliasChoices("kriging_method", "method"),
        description="Kriging method object. Defaults to ordinary kriging. Also accepts the legacy 'method' alias.",
    )
    source_filter: FilterInput | None = Field(
        default=None,
        description=(
            "Optional filter restricting kriging to a subset of the source samples. "
            "Provide a Filter with a 'where' condition, e.g. "
            "{'where': {'attribute': 'grade', 'operator': 'greater_than', 'threshold': 0.0}}."
        ),
    )
    target_filter: FilterInput | None = Field(
        default=None,
        description=(
            "Optional filter restricting kriging to a subset of the target object. "
            "Provide a Filter with a 'where' condition, e.g. "
            "{'where': {'attribute': 'domain', 'operator': 'in', 'values': ['LMS1', 'LMS2']}}."
        ),
    )
    block_discretization: BlockDiscretizationInput | None = Field(
        default=None,
        description="Optional sub-block discretization settings.",
    )

    @model_validator(mode="before")
    @classmethod
    def _check_aliases(cls, data: Any) -> Any:
        return _resolve_kriging_aliases(data)

    @property
    def search(self) -> SearchNeighborhood:
        """Backwards-compatible alias for `neighborhood`."""
        return self.neighborhood

    @property
    def method(self) -> SimpleKriging | OrdinaryKriging:
        """Backwards-compatible alias for `kriging_method`."""
        return self.kriging_method


class NeighborhoodBuildParams(BaseModel):
    """Shared inputs for neighborhood-based estimation without a variogram."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    target_object_id: str = Field(description="UUID of the existing target object in the workspace.")
    target_attribute: str = Field(description="Attribute to create or update with estimated values.")
    point_set_object_id: str = Field(
        description=(
            "UUID of the source object containing known sample values "
            "(for example a PointSet or DownholeIntervals; drillhole neighborhood limits require DownholeIntervals)."
        ),
    )
    point_set_attribute: str = Field(description="Existing numeric attribute containing the source sample values.")
    neighborhood: SearchInput = Field(
        validation_alias=AliasChoices("neighborhood", "search"),
        description="Search ellipsoid, rotation, and sample/sector/drillhole limits. Also accepts 'search'.",
    )
    source_filter: FilterInput | None = Field(default=None, description="Optional filter on source samples.")
    target_filter: FilterInput | None = Field(default=None, description="Optional filter on target locations.")

    @model_validator(mode="before")
    @classmethod
    def _check_aliases(cls, data: Any) -> Any:
        return _resolve_neighborhood_aliases(data)

    @property
    def search(self) -> SearchNeighborhood:
        """Backwards-compatible alias for `neighborhood`."""
        return self.neighborhood


class IDWBuildParams(NeighborhoodBuildParams):
    """Inputs for inverse distance weighting estimation."""

    power: float = Field(
        default=2.0,
        gt=0,
        allow_inf_nan=False,
        description="Positive inverse-distance exponent in ellipsoid space; defaults to classic IDW power 2.",
    )


def _check_idw_scenario(scenario: IDWParameters) -> IDWParameters:
    if not math.isfinite(scenario.power):
        raise ValueError("power must be finite.")
    return scenario


KrigingBuildInput = Annotated[KrigingBuildParams, BeforeValidator(_strict_model_validator(KrigingBuildParams))]
IDWBuildInput = Annotated[IDWBuildParams, BeforeValidator(_strict_model_validator(IDWBuildParams))]
KrigingScenario = Annotated[
    KrigingParameters,
    BeforeValidator(_validate_kriging_scenario),
    _AcceptEllipsoidAliasesSchema(),
]
IDWScenario = Annotated[
    IDWParameters,
    BeforeValidator(_strict_model_validator(IDWParameters)),
    AfterValidator(_check_idw_scenario),
    _AcceptEllipsoidAliasesSchema(),
]
