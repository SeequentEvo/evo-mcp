# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for compute task execution."""

import asyncio
import logging
from typing import Any

from evo.common import StaticContext
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
from evo.objects.typed import object_from_uuid
from evo.widgets import format_task_result_with_target
from fastmcp import Context
from pydantic import BaseModel, ConfigDict, Field

from evo_mcp.context import evo_context
from evo_mcp.utils.tool_support import (
    MCPFeedback,
    VariogramObjectId,
    build_links_from_metadata,
    get_workspace_environment,
)


class KrigingBuildParams(BaseModel):
    """Parameters for building a validated kriging payload."""

    model_config = ConfigDict(extra="ignore")

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
    search: SearchNeighborhood = Field(
        description="Search neighborhood parameters including ellipsoid and sample counts.",
    )
    method: SimpleKriging | OrdinaryKriging = Field(
        default_factory=OrdinaryKriging,
        description="Kriging method object. Defaults to ordinary kriging.",
    )
    target_region_filter: RegionFilter | None = Field(
        default=None,
        description="Optional region filter for the target object.",
    )
    block_discretisation: BlockDiscretisation | None = Field(
        default=None,
        description="Optional sub-block discretisation settings.",
    )


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
        params: KrigingBuildParams,
    ) -> dict[str, Any]:
        """Build a validated kriging payload from primitive inputs.

        Args:
            workspace_id: Workspace UUID where the task should run.
            params: Kriging build parameters including source, target, variogram, search neighborhood, and optional filters.

        Returns:
            A validated payload object suitable for kriging_run.
        """
        if not params.point_set_attribute or not params.point_set_attribute.strip():
            raise ValueError(
                "point_set_attribute must be a non-empty string. "
                "Specify the attribute name on the point set to use as the estimation input (e.g. 'CU_pct')."
            )
        if not params.target_attribute or not params.target_attribute.strip():
            raise ValueError(
                "target_attribute must be a non-empty string. "
                "Specify the name of the attribute to create on the target block model (e.g. 'OK_estimate')."
            )
        environment = await get_workspace_environment(workspace_id)
        context = StaticContext.from_environment(environment, evo_context.connector)
        source_object, target_object, variogram_object = await asyncio.gather(
            object_from_uuid(context, params.point_set_object_id),
            object_from_uuid(context, params.target_object_id),
            object_from_uuid(context, params.variogram_object_id),
        )
        source_attribute = source_object.attributes[params.point_set_attribute]
        payload = KrigingParameters(
            source=Source(object=source_object, attribute=source_attribute),
            target=Target.new_attribute(target_object, params.target_attribute),
            variogram=variogram_object,
            search=params.search,
            method=params.method,
            target_region_filter=params.target_region_filter,
            block_discretisation=params.block_discretisation,
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
        context = StaticContext.from_environment(environment, evo_context.connector)

        results = await run_compute(
            context, scenarios, preview=True, fb=MCPFeedback(ctx)
        )
        return {
            "status": "success",
            "scenarios_completed": len(results),
            "results": [
                _format_single_result(r, scenario, environment)
                for r, scenario in zip(results, scenarios)
            ],
        }
