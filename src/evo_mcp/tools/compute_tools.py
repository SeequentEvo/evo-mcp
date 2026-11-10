# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tool registration for compute tasks."""

from typing import Any

from fastmcp import Context

from evo_mcp.utils.compute_helpers import build_idw_parameters, build_kriging_parameters, run_estimation_scenarios
from evo_mcp.utils.compute_params import (
    IDWBuildInput,
    IDWScenario,
    KrigingBuildInput,
    KrigingScenario,
)
from evo_mcp.utils.compute_params import (
    IDWBuildParams as IDWBuildParams,
)
from evo_mcp.utils.compute_params import (
    KrigingBuildParams as KrigingBuildParams,
)
from evo_mcp.utils.compute_params import (
    NeighborhoodBuildParams as NeighborhoodBuildParams,
)


def register_compute_tools(mcp) -> None:
    """Register compute-related tools with the FastMCP server."""

    @mcp.tool()
    async def kriging_build_parameters(
        workspace_id: str,
        params: KrigingBuildInput,
    ) -> dict[str, Any]:
        """Build a validated kriging payload from primitive inputs.

        Args:
            workspace_id: Workspace UUID where the task should run.
            params: Kriging build parameters including source, target, variogram, search neighborhood, and optional filters.

        Returns:
            A validated payload object suitable for kriging_run.
        """
        return await build_kriging_parameters(workspace_id, params)

    @mcp.tool()
    async def idw_build_parameters(workspace_id: str, params: IDWBuildInput) -> dict[str, Any]:
        """Build validated inverse distance weighting (IDW) parameters for idw_run.

        Resolve the existing source and target objects, select nearby samples
        using the search neighborhood, and configure distance-weighting power.
        No variogram is required. This step does not execute estimation.
        """
        return await build_idw_parameters(workspace_id, params)

    @mcp.tool()
    async def idw_run(workspace_id: str, scenarios: list[IDWScenario], ctx: Context) -> dict[str, Any]:
        """Run inverse distance weighting (IDW) estimation scenarios in parallel.

        Accept payloads from idw_build_parameters. Estimates create or update
        attributes on the published target objects. Returns output references
        and viewer links in input order, with progress reported while running.
        """
        return await run_estimation_scenarios(workspace_id, scenarios, ctx)

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
        return await run_estimation_scenarios(workspace_id, scenarios, ctx)
