# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for compute task execution."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated, Any
from uuid import UUID


from evo.common import StaticContext
from evo.objects.typed import object_from_uuid
from evo.widgets import (
    format_task_result_with_target,
    get_portal_url,
    get_viewer_url,
)
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
from pydantic import Field
from evo_mcp.context import ensure_initialized, evo_context


logger = logging.getLogger(__name__)


TargetObjectId = Annotated[
    str,
    Field(
        description=(
            "UUID of the target object for kriging output. This should identify an "
            "existing BlockModel or Regular3DGrid in the provided workspace."
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
            "Target attribute name to create on the target object for kriging results."
        )
    ),
]

VariogramObjectId = Annotated[
    str,
    Field(
        description=("UUID of the variogram object to use for kriging."),
    ),
]


async def _get_workspace_environment(workspace_id: str) -> Any:
    await ensure_initialized()

    workspace_uuid = UUID(workspace_id)
    workspace = await evo_context.workspace_client.get_workspace(workspace_uuid)
    return workspace.get_environment()


def _build_links_from_metadata(environment: Any, object_id: str) -> dict[str, str]:
    return {
        "portal_url": get_portal_url(
            org_id=str(environment.org_id),
            workspace_id=str(environment.workspace_id),
            object_id=object_id,
            hub_url=environment.hub_url,
        ),
        "viewer_url": get_viewer_url(
            org_id=str(environment.org_id),
            workspace_id=str(environment.workspace_id),
            object_ids=object_id,
            hub_url=environment.hub_url,
        ),
    }


def register_compute_tools(mcp) -> None:
    """Register compute-related tools with the FastMCP server."""

    @mcp.tool()
    async def kriging_run(
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
        """Run a kriging compute task from primitive inputs.

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
            A compact summary of the compute result with target identifiers for follow-up work.
        """
        environment = await _get_workspace_environment(workspace_id)
        context = StaticContext.from_environment(environment, evo_context.connector)

        source_object, target_object, variogram_object = await asyncio.gather(
            object_from_uuid(context, point_set_object_id),
            object_from_uuid(context, target_object_id),
            object_from_uuid(context, variogram_object_id),
        )

        # Use typed attributes so compute receives canonical attribute expressions.
        source_attribute = source_object.attributes[point_set_attribute]

        compute_parameters = KrigingParameters(
            source=Source(object=source_object, attribute=source_attribute),
            target=Target.new_attribute(target_object, target_attribute),
            variogram=variogram_object,
            search=search,
            method=method,
            target_region_filter=target_region_filter,
            block_discretisation=block_discretisation,
        )

        result = await run_compute(context, compute_parameters, preview=True)

        links = _build_links_from_metadata(environment, target_object_id)
        requested_attribute = target_attribute

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
                    "operation": compute_parameters.target.attribute.operation,
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
