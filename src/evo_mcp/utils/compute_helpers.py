# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Payload construction and execution helpers for compute tools."""

import asyncio
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import jmespath
from evo.common import StaticContext
from evo.compute.tasks import run as run_compute
from evo.compute.tasks.common import (
    CreateAttribute,
    Filter,
    FilterCondition,
    FilterExpression,
    SearchNeighborhood,
    Source,
)
from evo.compute.tasks.geostatistics.idw import IDWParameters
from evo.compute.tasks.geostatistics.kriging import KrigingDiagnostics, KrigingParameters
from evo.objects import ObjectReference
from evo.objects.typed import DownholeIntervals, object_from_reference, object_from_uuid
from evo.widgets import format_task_result_with_target
from fastmcp import Context
from jmespath.exceptions import JMESPathError

from evo_mcp.context import get_evo_context
from evo_mcp.utils.compute_params import IDWBuildParams, KrigingBuildParams, NeighborhoodBuildParams
from evo_mcp.utils.tool_support import MCPFeedback, build_links_from_metadata, get_workspace_environment


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


def _check_drillhole_source(neighborhood: SearchNeighborhood, source_object: Any, point_set_object_id: str) -> None:
    active_drillhole_limits = _active_drillhole_limits(neighborhood)
    if active_drillhole_limits and not isinstance(source_object, DownholeIntervals):
        limits_str = ", ".join(active_drillhole_limits)
        raise ValueError(
            f"Drillhole neighborhood limits ({limits_str}) require a DownholeIntervals source object, "
            f"but point_set_object_id '{point_set_object_id}' resolved to "
            f"{source_object.__class__.__name__}."
        )


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

    payload = _normalize_neighborhood_payload(payload)

    target = payload.get("target")
    if isinstance(target, dict) and "diagnostics" in target and "diagnostics" not in payload:
        payload["diagnostics"] = target.pop("diagnostics")

    return payload


def _normalize_neighborhood_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Preserve input filters when SDK payloads cross MCP."""
    for side, field in (("source", "source_filter"), ("target", "target_filter")):
        container = payload.get(side)
        if isinstance(container, dict) and "filter" in container:
            raw_filter = container.pop("filter")
            payload[field] = (
                Filter.model_validate(raw_filter).model_dump(mode="json", exclude_none=True)
                if isinstance(raw_filter, Mapping)
                else raw_filter
            )

    return payload


def _available_attribute_names(object_: Any) -> list[str]:
    attributes = object_.attributes.values() if isinstance(object_.attributes, Mapping) else object_.attributes
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
            f"{field} '{attribute_name}' does not exist on the source object "
            f"({source_object.__class__.__name__}). Available attributes: {available}."
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
    _check_drillhole_source(params.neighborhood, source_object, params.point_set_object_id)
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
    _check_drillhole_source(params.neighborhood, source_object, params.point_set_object_id)
    source_attribute = source_object.attributes[params.point_set_attribute]
    if not getattr(source_attribute, "exists", True):
        available = _available_attribute_names(source_object)
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
        source_filter=_resolve_filter_attributes(params.source_filter, source_object, "source_filter"),
        target_filter=_resolve_filter_attributes(params.target_filter, target_object, "target_filter"),
        block_discretization=params.block_discretization,
    )
    return _normalize_kriging_payload(payload.model_dump(mode="json", exclude_none=True))


async def build_idw_parameters(workspace_id: str, params: IDWBuildParams) -> dict[str, Any]:
    """Resolve published objects and construct a round-trippable IDW payload."""
    source, target, source_filter, target_filter = await _resolve_estimation_inputs(workspace_id, params)
    payload = IDWParameters(
        source=source,
        target=target,
        neighborhood=params.neighborhood,
        power=params.power,
        source_filter=source_filter,
        target_filter=target_filter,
    )
    return _normalize_neighborhood_payload(payload.model_dump(mode="json", exclude_none=True))


def _object_identity(reference: str) -> tuple[UUID, UUID | str | None]:
    parsed = ObjectReference(reference)
    return parsed.workspace_id, parsed.object_id or parsed.object_path


def _canonical_selector_syntax(selector: str) -> Any:
    """Normalize equivalent JMESPath selector syntax (for example spacing or quote variants)."""
    stripped = selector.strip()
    try:
        ast = jmespath.compile(stripped).parsed
    except JMESPathError:
        return ("raw", stripped)
    return _selector_ast_key(ast)


def _selector_ast_key(node: Any) -> Any:
    if not isinstance(node, Mapping):
        return node
    node_type = node.get("type")
    children = tuple(_selector_ast_key(child) for child in node.get("children", ()))
    if node_type == "comparator" and node.get("value") == "eq" and len(children) == 2:
        children = tuple(sorted(children, key=repr))
    return (node_type, node.get("value"), children)


def _target_selector_document(target_object: Any) -> dict[str, Any]:
    """Construct a document view of target attributes so JMESPath selectors resolve to canonical keys."""
    as_dict = getattr(target_object, "as_dict", None)
    if callable(as_dict):
        raw_doc = as_dict()
        if isinstance(raw_doc, dict) and raw_doc:
            return raw_doc

    doc: dict[str, list[dict[str, str]]] = {}
    attributes_container = getattr(target_object, "attributes", None)
    if attributes_container is None:
        return doc
    items = (
        list(attributes_container.values()) if isinstance(attributes_container, Mapping) else list(attributes_container)
    )
    for attr in items:
        if not getattr(attr, "exists", True):
            continue
        name = getattr(attr, "name", None)
        if not isinstance(name, str):
            continue
        key = getattr(attr, "key", None)
        if not isinstance(key, str):
            col_uuid = getattr(attr, "block_model_column_uuid", None)
            key = str(col_uuid) if col_uuid is not None else name
        attr_ctx = getattr(attr, "_context", None)
        schema_path = getattr(attr_ctx, "schema_path", None)
        if not isinstance(schema_path, str) or not schema_path:
            schema_path = "attributes"
        doc.setdefault(schema_path, []).append({"name": name, "key": key})

    if "attributes" not in doc and len(doc) == 1:
        doc["attributes"] = next(iter(doc.values()))
    return doc


def _resolve_attribute_identity(spec: Any, target_object: Any | None) -> tuple[Any, ...]:
    """Resolve a CreateAttribute or UpdateAttribute to a canonical target-attribute identity."""
    if isinstance(spec, CreateAttribute) or getattr(spec, "operation", None) == "create":
        if target_object is not None and hasattr(target_object, "attributes"):
            try:
                existing = target_object.attributes[spec.name]
            except Exception:
                existing = None
            if existing is not None and getattr(existing, "exists", True):
                existing_key = getattr(existing, "key", None)
                if not isinstance(existing_key, str):
                    col_uuid = getattr(existing, "block_model_column_uuid", None)
                    existing_key = str(col_uuid) if col_uuid is not None else spec.name
                attr_ctx = getattr(existing, "_context", None)
                schema_path = getattr(attr_ctx, "schema_path", None)
                path = schema_path if isinstance(schema_path, str) and schema_path else "attributes"
                return ("attr", path, existing_key)
        return ("name", spec.name)

    reference = spec.reference
    if target_object is not None:
        doc = _target_selector_document(target_object)
        if doc:
            root_prefix = reference.split("[", 1)[0].strip() or "attributes"
            if root_prefix == "attributes" and "attributes" not in doc:
                for candidate_path in ("cell_attributes", "locations.attributes", "intervals.attributes"):
                    if candidate_path in doc:
                        root_prefix = candidate_path
                        break
            try:
                matched = jmespath.search(reference, doc)
            except JMESPathError:
                matched = None
            if isinstance(matched, Mapping):
                matched = [matched]
            if isinstance(matched, list) and len(matched) == 1 and isinstance(matched[0], Mapping):
                canonical_id = matched[0].get("key") or matched[0].get("name")
                if isinstance(canonical_id, str):
                    return ("attr", root_prefix, canonical_id)
        if hasattr(target_object, "attributes"):
            try:
                by_name = target_object.attributes[reference.strip()]
            except Exception:
                by_name = None
            if by_name is not None and getattr(by_name, "exists", True):
                key = getattr(by_name, "key", None)
                canonical_id = key if isinstance(key, str) else getattr(by_name, "name", reference.strip())
                attr_ctx = getattr(by_name, "_context", None)
                schema_path = getattr(attr_ctx, "schema_path", None)
                path = schema_path if isinstance(schema_path, str) and schema_path else "attributes"
                return ("attr", path, canonical_id)

    return ("selector", _canonical_selector_syntax(reference))


def _scenario_target_specs(scenario: Any) -> list[Any]:
    specs = [scenario.target.attribute]
    if isinstance(scenario, KrigingParameters) and scenario.diagnostics is not None:
        for field in KrigingDiagnostics.model_fields:
            if (diag_spec := getattr(scenario.diagnostics, field)) is not None:
                specs.append(diag_spec)
    return specs


async def _estimation_outputs(context: Any, scenarios: list[Any]) -> list[tuple[Any, ...]]:
    target_groups: dict[tuple[UUID, UUID | str | None], list[Any]] = {}
    for scenario in scenarios:
        target_groups.setdefault(_object_identity(scenario.target.object), []).append(scenario)

    resolved_targets: dict[tuple[UUID, UUID | str | None], Any] = {}
    multi_scenario_targets = [
        (obj_id, group[0].target.object)
        for obj_id, group in target_groups.items()
        if sum(len(_scenario_target_specs(s)) for s in group) > 1
        and any(getattr(spec, "operation", None) == "update" for s in group for spec in _scenario_target_specs(s))
    ]
    if multi_scenario_targets:
        fetched = await asyncio.gather(
            *(
                object_from_uuid(context, str(obj_id[1]))
                if isinstance(obj_id[1], UUID)
                else object_from_reference(context, ref)
                for obj_id, ref in multi_scenario_targets
            ),
            return_exceptions=True,
        )
        for (obj_id, _), target_obj in zip(multi_scenario_targets, fetched):
            if not isinstance(target_obj, BaseException):
                resolved_targets[obj_id] = target_obj

    outputs: list[tuple[Any, ...]] = []
    for scenario in scenarios:
        obj_id = _object_identity(scenario.target.object)
        target_obj = resolved_targets.get(obj_id)
        for spec in _scenario_target_specs(scenario):
            outputs.append((*obj_id, *_resolve_attribute_identity(spec, target_obj)))
    return outputs


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
    collect_outputs: Callable[[Any, list[Any]], Any],
    output_kind: str,
    format_result: Callable[[Any, Any, Any], dict[str, Any]],
) -> dict[str, Any]:
    if not scenarios:
        raise ValueError("Must specify at least one scenario.")

    environment = await get_workspace_environment(workspace_id)
    for scenario in scenarios:
        _check_workspace_scope(environment, scenario)
    evo_context = await get_evo_context()
    context = StaticContext.from_environment(environment, evo_context.connector)
    outputs = await collect_outputs(context, scenarios)
    if len(set(outputs)) < len(outputs):
        raise ValueError(f"Concurrent scenarios must write to distinct {output_kind}.")
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
        collect_outputs=_estimation_outputs,
        output_kind="target attributes",
        format_result=_format_single_result,
    )
