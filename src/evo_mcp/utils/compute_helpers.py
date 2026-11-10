# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Payload construction and execution helpers for compute tools."""

import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from evo.common import StaticContext
from evo.compute.tasks import run as run_compute
from evo.compute.tasks.common import Filter, FilterCondition, FilterExpression, Source
from evo.compute.tasks.geostatistics.idw import IDWParameters
from evo.compute.tasks.geostatistics.kriging import KrigingParameters
from evo.objects import ObjectReference
from evo.objects.typed import object_from_uuid
from evo.widgets import format_task_result_with_target
from fastmcp import Context

from evo_mcp.context import get_evo_context
from evo_mcp.utils.compute_params import IDWBuildParams, KrigingBuildParams, NeighborhoodBuildParams
from evo_mcp.utils.tool_support import MCPFeedback, build_links_from_metadata, get_workspace_environment


def _normalize_kriging_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize payload shape for MCP round-trips.

    The evo-objects SDK uses different field names compared to evo-compute for some kriging parameters.

    - `search` -> `neighborhood`, `method` -> `kriging_method`.
    - SearchNeighborhood serialization emits `ellipsoid_ranges`, while
      Ellipsoid construction expects `ranges`.
    - KrigingParameters serializes `source_filter`/`target_filter` into the
      backend-shaped `source.filter`/`target.filter` (the fields are excluded
      from the model dump). Relocate them back to the top-level input fields so
      the filters survive the `kriging_build_parameters` -> `kriging_run`
      round-trip instead of being silently dropped on re-parse.
    """
    if "search" in payload and "neighborhood" not in payload:
        payload["neighborhood"] = payload.pop("search")

    if "method" in payload and "kriging_method" not in payload:
        payload["kriging_method"] = payload.pop("method")

    return _normalize_neighborhood_payload(payload)


def _normalize_neighborhood_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve input filters and ellipsoid ranges when SDK payloads cross MCP."""
    for side, field in (("source", "source_filter"), ("target", "target_filter")):
        container = payload.get(side)
        if isinstance(container, dict) and "filter" in container:
            payload[field] = container.pop("filter")

    neighborhood = payload.get("neighborhood")
    if not isinstance(neighborhood, dict):
        return payload

    ellipsoid = neighborhood.get("ellipsoid")
    if not isinstance(ellipsoid, dict):
        return payload

    if "ellipsoid_ranges" in ellipsoid and "ranges" not in ellipsoid:
        ellipsoid["ranges"] = ellipsoid.pop("ellipsoid_ranges")

    return payload


def _available_attribute_names(object_: Any) -> list[str]:
    attributes = object_.attributes.values() if isinstance(object_.attributes, dict) else object_.attributes
    return [
        name
        for attribute in attributes
        if getattr(attribute, "exists", True) and isinstance(name := getattr(attribute, "name", None), str)
    ]


def _existing_source_attribute(source_object: Any, attribute_name: str, field: str = "point_set_attribute") -> Any:
    source_attribute = source_object.attributes[attribute_name]
    if not getattr(source_attribute, "exists", True):
        available = _available_attribute_names(source_object)
        raise ValueError(
            f"{field} '{attribute_name}' does not exist on the source point set. Available attributes: {available}."
        )
    return source_attribute


def _resolve_filter_attributes(filter_: Filter | None, object_: Any, field: str = "filter") -> Filter | None:
    if filter_ is None:
        return None

    def resolve(expression: FilterExpression) -> FilterExpression:
        if isinstance(expression, FilterCondition):
            try:
                attribute = object_.attributes[expression.attribute]
            except KeyError:
                attribute = None
            if attribute is not None and getattr(attribute, "exists", True):
                return FilterCondition.model_validate({**expression.model_dump(), "attribute": attribute})
            if "[" in expression.attribute:
                return expression
            available = _available_attribute_names(object_)
            raise ValueError(
                f"{field} attribute '{expression.attribute}' does not exist. Available attributes: {available}."
            )
        return expression.model_copy(update={"filters": [resolve(child) for child in expression.filters]})

    return filter_.model_copy(update={"where": resolve(filter_.where)})


async def _resolve_estimation_inputs(
    workspace_id: str, params: NeighborhoodBuildParams
) -> tuple[Source, Any, Filter | None, Filter | None]:
    for field in ("point_set_attribute", "target_attribute"):
        if not getattr(params, field).strip():
            raise ValueError(f"{field} must be a non-empty string.")

    environment = await get_workspace_environment(workspace_id)
    evo_context = await get_evo_context()
    context = StaticContext.from_environment(environment, evo_context.connector)
    source_object, target_object = await asyncio.gather(
        object_from_uuid(context, params.point_set_object_id),
        object_from_uuid(context, params.target_object_id),
    )
    source_attribute = _existing_source_attribute(source_object, params.point_set_attribute)
    return (
        Source(object=source_object, attribute=source_attribute),
        target_object.attributes[params.target_attribute],
        _resolve_filter_attributes(params.source_filter, source_object, "source_filter"),
        _resolve_filter_attributes(params.target_filter, target_object, "target_filter"),
    )


async def build_kriging_parameters(workspace_id: str, params: KrigingBuildParams) -> dict[str, Any]:
    """Resolve published objects and construct a round-trippable kriging payload."""
    if not params.point_set_attribute or not params.point_set_attribute.strip():
        raise ValueError(
            "point_set_attribute must be a non-empty string. "
            "Specify the attribute name on the point set to use as the estimation input (e.g. 'CU_pct')."
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
    source_attribute = source_object.attributes[params.point_set_attribute]
    if not getattr(source_attribute, "exists", True):
        available = _available_attribute_names(source_object)
        raise ValueError(
            f"point_set_attribute '{params.point_set_attribute}' does not exist on the source point set. "
            f"A kriging source must reference an existing attribute containing the sample values. "
            f"Available attributes: {available}."
        )
    payload = KrigingParameters(
        source=Source(object=source_object, attribute=source_attribute),
        target=target_object.attributes[params.target_attribute],
        variogram=variogram_object,
        search=params.search,
        method=params.method,
        source_filter=_resolve_filter_attributes(params.source_filter, source_object, "source_filter"),
        target_filter=_resolve_filter_attributes(params.target_filter, target_object, "target_filter"),
        block_discretization=params.block_discretization,
    )
    return _normalize_kriging_payload(payload.model_dump(mode="json"))


async def build_idw_parameters(workspace_id: str, params: IDWBuildParams) -> dict[str, Any]:
    """Resolve published objects and construct a round-trippable IDW payload."""
    source, target, source_filter, target_filter = await _resolve_estimation_inputs(workspace_id, params)
    payload = IDWParameters(
        source=source,
        target=target,
        neighborhood=params.search,
        power=params.power,
        source_filter=source_filter,
        target_filter=target_filter,
    )
    return _normalize_neighborhood_payload(payload.model_dump(mode="json"))


def _object_identity(reference: str) -> tuple[UUID, UUID | str | None]:
    parsed = ObjectReference(reference)
    return parsed.workspace_id, parsed.object_id or parsed.object_path


def _estimation_output(scenario: Any) -> tuple[Any, ...]:
    attribute = scenario.target.attribute
    key = attribute.name if attribute.operation == "create" else attribute.reference
    return (*_object_identity(scenario.target.object), key)


def _object_references(scenario: Any) -> list[str]:
    references = [scenario.source.object, scenario.target.object]
    if isinstance(scenario, KrigingParameters):
        references.append(scenario.variogram)
    return references


def _check_workspace_scope(environment: Any, scenario: Any) -> None:
    expected = (
        urlsplit(str(environment.hub_url)).netloc.lower(),
        UUID(str(environment.org_id)),
        UUID(str(environment.workspace_id)),
    )
    for reference in _object_references(scenario):
        parsed = ObjectReference(reference)
        if (urlsplit(parsed.hub_url).netloc.lower(), parsed.org_id, parsed.workspace_id) != expected:
            raise ValueError(
                f"Object reference '{reference}' is outside workspace {environment.workspace_id}. "
                "Rebuild the scenario for this workspace."
            )


def _format_single_result(result: Any, scenario: Any, environment: Any) -> dict[str, Any]:
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


async def _run_scenarios(
    workspace_id: str,
    scenarios: list[Any],
    ctx: Context,
    *,
    output_identity: Callable[[Any], tuple[Any, ...]],
    output_kind: str,
    format_result: Callable[[Any, Any, Any], dict[str, Any]],
) -> dict[str, Any]:
    if not scenarios:
        raise ValueError("Must specify at least one scenario.")
    outputs = [output_identity(scenario) for scenario in scenarios]
    if len(set(outputs)) < len(outputs):
        raise ValueError(f"Concurrent scenarios must write to distinct {output_kind}.")

    environment = await get_workspace_environment(workspace_id)
    for scenario in scenarios:
        _check_workspace_scope(environment, scenario)
    evo_context = await get_evo_context()
    context = StaticContext.from_environment(environment, evo_context.connector)
    results = await run_compute(context, scenarios, preview=True, fb=MCPFeedback(ctx))
    return {
        "status": "success",
        "scenarios_completed": len(results),
        "results": [format_result(result, scenario, environment) for result, scenario in zip(results, scenarios)],
    }


async def run_estimation_scenarios(workspace_id: str, scenarios: list[Any], ctx: Context) -> dict[str, Any]:
    """Run validated estimation scenarios and return results in input order."""
    return await _run_scenarios(
        workspace_id,
        scenarios,
        ctx,
        output_identity=_estimation_output,
        output_kind="target attributes",
        format_result=_format_single_result,
    )
