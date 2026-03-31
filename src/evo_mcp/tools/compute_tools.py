# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for compute task execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any

from pydantic import Field


from evo.common import StaticContext
from evo.objects.typed import object_from_uuid
from evo.widgets import format_task_result_with_target
from evo.compute.tasks import run as run_compute
from evo.compute.tasks.common import (
    SearchNeighborhood,
    Source,
    Target,
)
from evo.compute.tasks.kriging import (
    BlockDiscretisation,
    KrigingParameters,
    OrdinaryKriging,
    RegionFilter,
    SimpleKriging,
)
from evo_mcp.context import evo_context
from evo_mcp.utils.tool_support import (
    VariogramObjectId,
    get_workspace_environment,
    build_links_from_metadata,
)

TargetObjectId = Annotated[
    str,
    Field(
        description=(
            "UUID of the target object for an estimation or spatial-validation workflow. "
            "For kriging, this should identify an existing BlockModel or Regular3DGrid in the provided workspace."
        ),
    ),
]

PointSetAttributeName = Annotated[
    str,
    Field(
        description=(
            "Existing numeric source attribute name on the point set object, "
            "for example 'CU_pct'."
        )
    ),
]

PointSetObjectId = Annotated[
    str,
    Field(
        description=(
            "UUID of the source PointSet object containing known sample values."
        ),
    ),
]

TargetAttributeName = Annotated[
    str,
    Field(
        description=(
            "Target attribute name to create or update on the target object for estimation results."
        )
    ),
]


logger = logging.getLogger(__name__)


def _normalize_kriging_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize payload shape for MCP round-trips.

    - Canonicalize field names expected by `kriging_run`:
      `search` -> `neighborhood`, `method` -> `kriging_method`.
    - SearchNeighborhood serialization emits `ellipsoid_ranges`, while
      Ellipsoid construction expects `ranges`.
    """
    if "search" in payload and "neighborhood" not in payload:
        payload["neighborhood"] = payload.pop("search")

    if "method" in payload and "kriging_method" not in payload:
        payload["kriging_method"] = payload.pop("method")

    neighborhood = payload.get("neighborhood")
    if not isinstance(neighborhood, dict):
        return payload

    ellipsoid = neighborhood.get("ellipsoid")
    if not isinstance(ellipsoid, dict):
        return payload

    if "ellipsoid_ranges" in ellipsoid and "ranges" not in ellipsoid:
        ellipsoid["ranges"] = ellipsoid.pop("ellipsoid_ranges")

    return payload


def register_compute_tools(mcp) -> None:
    """Register compute-related tools with the FastMCP server."""

    @mcp.tool()
    async def kriging_build_parameters(
        workspace_id: str,
        target_object_id: TargetObjectId,
        target_attribute: TargetAttributeName,
        point_set_object_id: PointSetObjectId,
        point_set_attribute: PointSetAttributeName,
        variogram_object_id: VariogramObjectId,
        search: SearchNeighborhood,
        method: SimpleKriging | OrdinaryKriging = OrdinaryKriging(),
        target_region_filter: RegionFilter | None = None,
        block_discretisation: BlockDiscretisation | None = None,
    ) -> dict[str, Any]:
        """Build a validated kriging payload from primitive inputs.

        Args:
            workspace_id: Workspace UUID where the task should run.
            target_object_id: UUID of the target BlockModel or Regular3DGrid object.
            target_attribute: Name of the target attribute to create.
            point_set_object_id: UUID of the source PointSet object.
            point_set_attribute: Existing source attribute name on the PointSet.
            variogram_object_id: UUID of the variogram object.
            search: Search neighborhood parameters including ellipsoid and sample counts.
            method: Kriging method object. Defaults to ordinary kriging.
            target_region_filter: Optional region filter for the target object.
            block_discretisation: Optional sub-block discretisation settings.

        Returns:
            A validated payload object suitable for kriging_run.
        """
        if not point_set_attribute or not point_set_attribute.strip():
            raise ValueError(
                "point_set_attribute must be a non-empty string. "
                "Specify the attribute name on the point set to use as the estimation input (e.g. 'CU_pct')."
            )
        if not target_attribute or not target_attribute.strip():
            raise ValueError(
                "target_attribute must be a non-empty string. "
                "Specify the name of the attribute to create on the target block model (e.g. 'OK_estimate')."
            )
        environment = await get_workspace_environment(workspace_id)
        context = StaticContext.from_environment(environment, evo_context.connector)
        source_object, target_object, variogram_object = await asyncio.gather(
            object_from_uuid(context, point_set_object_id),
            object_from_uuid(context, target_object_id),
            object_from_uuid(context, variogram_object_id),
        )
        source_attribute = source_object.attributes[point_set_attribute]
        payload = KrigingParameters(
            source=Source(object=source_object, attribute=source_attribute),
            target=Target.new_attribute(target_object, target_attribute),
            variogram=variogram_object,
            search=search,
            method=method,
            target_region_filter=target_region_filter,
            block_discretisation=block_discretisation,
        )

        return _normalize_kriging_payload(payload.model_dump(mode="json"))

    def _format_single_result(
        result: Any,
        scenario: KrigingParameters,
        environment: Any,
    ) -> dict[str, Any]:
        target_reference = str(scenario.target.object)
        target_object_id = target_reference.rstrip("/").split("/")[-1].split("?")[0]
        links = build_links_from_metadata(environment, target_object_id)
        requested_attribute = getattr(
            scenario.target.attribute, "name", result.attribute_name
        )
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
        scenarios: list[KrigingParameters],
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
        context = StaticContext.from_environment(environment, evo_context.connector)

        results = await run_compute(context, scenarios, preview=True)
        return {
            "status": "success",
            "scenarios_completed": len(results),
            "results": [
                _format_single_result(r, scenario, environment)
                for r, scenario in zip(results, scenarios)
            ],
        }
