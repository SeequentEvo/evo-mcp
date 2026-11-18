# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for compute task execution."""

import asyncio
import logging
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Annotated, Any

from evo.common import StaticContext
from evo.compute.tasks import run as run_compute
from evo.compute.tasks.common import (
    Filter,
    SearchNeighborhood,
    Source,
)
from evo.compute.tasks.geostatistics.kriging import (
    BlockDiscretization,
    KrigingParameters,
    OrdinaryKriging,
    SimpleKriging,
)
from evo.objects.typed import DownholeIntervals, object_from_uuid
from evo.widgets import format_task_result_with_target
from fastmcp import Context
from pydantic import (
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

from evo_mcp.context import get_evo_context
from evo_mcp.utils.tool_support import (
    MCPFeedback,
    VariogramObjectId,
    build_links_from_metadata,
    get_workspace_environment,
)

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
    def _validate(value: Any) -> Any:
        if isinstance(value, Mapping):
            return model.model_validate(value, extra="forbid")
        return value

    return _validate


def _resolve_kriging_aliases(data: Any) -> Any:
    """Reject conflicting canonical/legacy alias pairs and normalize identical ones."""
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

    for key in ("neighborhood", "search"):
        if key in cleaned and isinstance(cleaned[key], Mapping):
            cleaned[key] = _clean_search_mapping(cleaned[key])

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
        if "neighborhood" in props:
            neighborhood_schema = handler.resolve_ref_schema(props["neighborhood"])
            cls._patch_neighborhood_schema(neighborhood_schema, handler)


SearchInput = Annotated[
    SearchNeighborhood,
    BeforeValidator(_validate_search),
    _AcceptEllipsoidAliasesSchema(),
]
KrigingMethodInput = Annotated[SimpleKriging | OrdinaryKriging, BeforeValidator(_validate_kriging_method)]
FilterInput = Annotated[Filter, BeforeValidator(_strict_model_validator(Filter))]
BlockDiscretizationInput = Annotated[BlockDiscretization, BeforeValidator(_strict_model_validator(BlockDiscretization))]
KrigingScenario = Annotated[
    KrigingParameters,
    BeforeValidator(_validate_kriging_scenario),
    _AcceptEllipsoidAliasesSchema(),
]


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


logger = logging.getLogger(__name__)


def _active_drillhole_limits(neighborhood: SearchNeighborhood) -> list[str]:
    """Return the names of active drillhole constraints on `neighborhood`."""
    limits: list[str] = []
    if neighborhood.max_samples_per_drillhole is not None:
        limits.append("max_samples_per_drillhole")
    if neighborhood.max_drillholes is not None:
        limits.append("max_drillholes")
    if neighborhood.min_drillholes is not None and neighborhood.min_drillholes > 0:
        limits.append("min_drillholes")
    if neighborhood.drillhole_limit_scope in ("quadrant", "octant"):
        limits.append("drillhole_limit_scope")
    return limits


def _normalize_kriging_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize KrigingParameters serialization for MCP round-trips.

    `KrigingParameters.model_dump(mode="json")` natively emits canonical
    `neighborhood` (with `ellipsoid_ranges` and `rotation`) and `kriging_method`,
    which `SearchNeighborhood` and `KrigingParameters` re-validate directly.

    `source_filter` and `target_filter` serialize into backend-shaped
    `source.filter` and `target.filter` (and are excluded at the top level).
    Relocate them back to top-level input fields so filters survive the
    `kriging_build_parameters` -> `kriging_run` round-trip.
    """
    if "search" in payload and "neighborhood" not in payload:
        payload["neighborhood"] = payload.pop("search")

    if "method" in payload and "kriging_method" not in payload:
        payload["kriging_method"] = payload.pop("method")

    for side, field in (("source", "source_filter"), ("target", "target_filter")):
        container = payload.get(side)
        if isinstance(container, dict) and "filter" in container:
            raw_filter = container.pop("filter")
            payload[field] = (
                Filter.model_validate(raw_filter).model_dump(mode="json", exclude_none=True)
                if isinstance(raw_filter, Mapping)
                else raw_filter
            )

    target = payload.get("target")
    if isinstance(target, dict) and "diagnostics" in target and "diagnostics" not in payload:
        payload["diagnostics"] = target.pop("diagnostics")

    return payload


def register_compute_tools(mcp) -> None:
    """Register compute-related tools with the FastMCP server."""

    @mcp.tool()
    async def kriging_build_parameters(
        workspace_id: str,
        params: KrigingBuildParams,
    ) -> dict[str, Any]:
        """Build a validated kriging payload from primitive inputs.

        Args:
            workspace_id: Workspace UUID where the task should run.
            params: Kriging build parameters including source, target, variogram,
                neighborhood, kriging method, and optional filters or discretization.

        Returns:
            A validated payload object suitable for kriging_run.
        """
        if not params.point_set_attribute or not params.point_set_attribute.strip():
            raise ValueError(
                "point_set_attribute must be a non-empty string. "
                "Specify the attribute name on the source object (e.g. PointSet or DownholeIntervals) "
                "to use as the estimation input (e.g. 'CU_pct')."
            )
        if not params.target_attribute or not params.target_attribute.strip():
            raise ValueError(
                "target_attribute must be a non-empty string. "
                "Specify the name of the attribute to create or update on the target block model (e.g. 'OK_estimate')."
            )
        environment = await get_workspace_environment(workspace_id)
        evo_context = await get_evo_context()
        context = StaticContext.from_environment(environment, evo_context.connector)
        source_object, target_object, variogram_object = await asyncio.gather(
            object_from_uuid(context, params.point_set_object_id),
            object_from_uuid(context, params.target_object_id),
            object_from_uuid(context, params.variogram_object_id),
        )
        active_drillhole_limits = _active_drillhole_limits(params.neighborhood)
        if active_drillhole_limits and not isinstance(source_object, DownholeIntervals):
            limits_str = ", ".join(active_drillhole_limits)
            raise ValueError(
                f"Drillhole neighborhood limits ({limits_str}) require a DownholeIntervals source object, "
                f"but point_set_object_id '{params.point_set_object_id}' resolved to "
                f"{source_object.__class__.__name__}."
            )
        source_attribute = source_object.attributes[params.point_set_attribute]
        if not getattr(source_attribute, "exists", True):
            attributes = (
                source_object.attributes.values()
                if isinstance(source_object.attributes, Mapping)
                else source_object.attributes
            )
            available = [
                name
                for a in attributes
                if getattr(a, "exists", True) and isinstance(name := getattr(a, "name", None), str)
            ]
            raise ValueError(
                f"point_set_attribute '{params.point_set_attribute}' does not exist on the source object "
                f"({source_object.__class__.__name__}). "
                f"A kriging source must reference an existing attribute containing the sample values. "
                f"Available attributes: {available}."
            )
        payload = KrigingParameters(
            source=Source(object=source_object, attribute=source_attribute),
            target=target_object.attributes[params.target_attribute],
            variogram=variogram_object,
            neighborhood=params.neighborhood,
            kriging_method=params.kriging_method,
            source_filter=params.source_filter,
            target_filter=params.target_filter,
            block_discretization=params.block_discretization,
        )

        return _normalize_kriging_payload(payload.model_dump(mode="json", exclude_none=True))

    def _format_single_result(
        result: Any,
        scenario: KrigingParameters,
        environment: Any,
    ) -> dict[str, Any]:
        target_reference = str(scenario.target.object)
        target_object_id = target_reference.rstrip("/").split("/")[-1].split("?")[0]
        links = build_links_from_metadata(environment, target_object_id)
        requested_attribute = getattr(scenario.target.attribute, "name", result.attribute_name)
        return {
            "status": "success",
            "message": result.message,
            "target": {
                "name": result.target_name,
                "reference": result.target_reference,
                "schema_id": str(result.schema),
                "locator": {
                    "org_id": str(environment.org_id),
                    "workspace_id": str(environment.workspace_id),
                    "object_id": target_object_id,
                    "hub_url": environment.hub_url,
                },
                "attribute": {
                    "operation": scenario.target.attribute.operation,
                    "name": result.attribute_name,
                    "requested": requested_attribute,
                },
            },
            "presentation": {
                "html": format_task_result_with_target(result),
                "portal_url": links["portal_url"],
                "viewer_url": links["viewer_url"],
            },
        }

    @mcp.tool()
    async def kriging_run(
        workspace_id: str,
        scenarios: list[KrigingScenario],
        ctx: Context,
    ) -> dict[str, Any]:
        """Run one or more kriging compute tasks in parallel.

        Args:
            workspace_id: Workspace UUID where all tasks should run.
            scenarios: List of KrigingParameters objects, as built by kriging_build_parameters.

        Returns:
            A list of result summaries in the same order as the input scenarios.
        """
        if len(scenarios) == 0:
            raise ValueError("Must specify at least one scenario.")

        environment = await get_workspace_environment(workspace_id)
        evo_context = await get_evo_context()
        context = StaticContext.from_environment(environment, evo_context.connector)

        results = await run_compute(context, scenarios, preview=True, fb=MCPFeedback(ctx))
        return {
            "status": "success",
            "scenarios_completed": len(results),
            "results": [_format_single_result(r, scenario, environment) for r, scenario in zip(results, scenarios)],
        }
