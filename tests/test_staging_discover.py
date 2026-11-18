# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the merged ``staging_discover`` tool (Option C).

``staging_discover`` replaces the previous ``staging_list_object_types`` +
``staging_list_interactions`` pair with a single discovery entry point:

- no argument  -> list all stageable object types + lifecycle capabilities
- object_type  -> list the interactions (and their param schemas) for that type
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError

from evo_mcp.session.registry import ObjectRegistry
from evo_mcp.staging.objects.search_neighborhood import SearchNeighborhoodData
from evo_mcp.staging.service import StagingService
from evo_mcp.tools import register_object_staging_tools


def _build_staging_server() -> FastMCP:
    mcp = FastMCP("staging-test")
    register_object_staging_tools(mcp)
    return mcp


def _call(mcp: FastMCP, **kwargs) -> dict:
    result = asyncio.run(mcp.call_tool("staging_discover", kwargs))
    return result.structured_content


def test_discover_without_argument_lists_object_types():
    mcp = _build_staging_server()
    payload = _call(mcp)
    assert "object_types" in payload
    types = {o["object_type"] for o in payload["object_types"]}
    # The registry ships these built-in stageable types.
    assert {"variogram", "point_set"} <= types
    # Each entry advertises its lifecycle capabilities.
    sample = payload["object_types"][0]
    assert {"object_type", "display_name", "supports_create", "supports_import", "publish_modes"} <= sample.keys()
    capabilities = {item["object_type"]: item["supports_create"] for item in payload["object_types"]}
    assert capabilities["block_model"] is False
    assert capabilities["variogram"] is True


def test_discover_with_object_type_lists_interactions():
    mcp = _build_staging_server()
    payload = _call(mcp, object_type="variogram")
    assert payload["object_type"] == "variogram"
    assert "display_name" in payload
    interactions = {item["name"]: item for item in payload["interactions"]}
    assert "get_structure_details" in interactions
    assert "parameters_schema" in interactions["get_structure_details"]
    assert "structure_index" in interactions["get_structure_details"]["parameters_schema"]["properties"]


def test_old_discovery_tools_are_removed():
    mcp = _build_staging_server()
    names = {t.name for t in asyncio.run(mcp.list_tools())}
    assert "staging_discover" in names
    # The two tools merged into staging_discover must no longer be registered.
    assert "staging_list_object_types" not in names
    assert "staging_list_interactions" not in names


def _mock_staging_context() -> SimpleNamespace:
    staging = StagingService()
    return SimpleNamespace(
        object_staging=staging,
        object_registry=ObjectRegistry(staging),
    )


def test_staged_search_neighborhood_supports_sector_and_drillhole_limits():
    mcp = _build_staging_server()
    fake_ctx = _mock_staging_context()

    with patch("evo_mcp.context.get_evo_context", new=AsyncMock(return_value=fake_ctx)):
        with (
            patch("evo_mcp.staging.objects.search_neighborhood.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
            patch("evo_mcp.staging.objects.base.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
            patch("evo_mcp.tools.object_staging_tools.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
        ):
            created = asyncio.run(
                mcp.call_tool(
                    "staging_create_object",
                    {
                        "object_type": "search_neighborhood",
                        "params": {
                            "object_name": "dh_neighborhood",
                            "major": 200.0,
                            "semi_major": 150.0,
                            "minor": 100.0,
                            "dip_azimuth": 45.0,
                            "dip": 30.0,
                            "pitch": 15.0,
                            "max_samples": 24,
                            "min_samples": 4,
                            "max_empty_octants": 4,
                            "max_samples_per_octant": 4,
                            "max_samples_per_drillhole": 2,
                            "max_drillholes_per_estimate": 6,
                            "min_drillholes_per_estimate": 2,
                            "drillhole_limit_scope": "octant",
                        },
                    },
                )
            ).structured_content

            config = created["result"]["configuration"]
            assert config["max_drillholes"] == 6
            assert config["min_drillholes"] == 2
            assert config["drillhole_limit_scope"] == "octant"
            assert config["max_samples_per_drillhole"] == 2
            assert config["max_samples_per_octant"] == 4

            summary = asyncio.run(
                mcp.call_tool(
                    "staging_invoke_interaction",
                    {"object_name": "dh_neighborhood", "interaction_name": "get_summary"},
                )
            ).structured_content
            assert summary["result"]["configuration"] == config

    _, payload = fake_ctx.object_registry.get_payload("dh_neighborhood")
    compute_sn = payload.to_compute_neighborhood()
    assert compute_sn.max_drillholes == 6
    assert compute_sn.max_drillholes_per_estimate == 6
    assert compute_sn.min_drillholes == 2
    assert compute_sn.drillhole_limit_scope == "octant"


def test_variogram_create_search_neighborhood_forwards_sector_and_drillhole_limits():
    mcp = _build_staging_server()
    fake_ctx = _mock_staging_context()

    with (
        patch("evo_mcp.staging.objects.variogram.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
        patch("evo_mcp.staging.objects.base.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
        patch("evo_mcp.tools.object_staging_tools.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
    ):
        asyncio.run(
            mcp.call_tool(
                "staging_create_object",
                {
                    "object_type": "variogram",
                    "params": {
                        "object_name": "cu_variogram",
                        "sill": 1.0,
                        "nugget": 0.2,
                        "structures": [
                            {
                                "variogram_type": "spherical",
                                "contribution": 0.8,
                                "anisotropy": {
                                    "ellipsoid_ranges": {"major": 150.0, "semi_major": 100.0, "minor": 50.0},
                                    "rotation": {"dip_azimuth": 30.0, "dip": 15.0, "pitch": 0.0},
                                },
                            }
                        ],
                    },
                },
            )
        )

        derived = asyncio.run(
            mcp.call_tool(
                "staging_invoke_interaction",
                {
                    "object_name": "cu_variogram",
                    "interaction_name": "create_search_neighborhood",
                    "params": {
                        "object_name": "derived_sn",
                        "scale_factor": 2.0,
                        "max_samples": 16,
                        "min_samples": 4,
                        "max_samples_per_quadrant": 4,
                        "max_samples_per_drillhole": 2,
                        "max_drillholes": 4,
                        "min_drillholes": 2,
                        "drillhole_limit_scope": "quadrant",
                    },
                },
            )
        ).structured_content

    config = derived["result"]["configuration"]
    assert config["major"] == 300.0
    assert config["semi_major"] == 200.0
    assert config["minor"] == 100.0
    assert config["max_samples_per_quadrant"] == 4
    assert config["max_samples_per_drillhole"] == 2
    assert config["max_drillholes"] == 4
    assert config["min_drillholes"] == 2
    assert config["drillhole_limit_scope"] == "quadrant"


@pytest.mark.parametrize(
    "bad_params",
    [
        {"min_samples": 0},
        {"drillhole_limit_scope": "quadrant"},
        {"max_drillholes": 4, "max_drillholes_per_estimate": 6},
        {"min_samples": 17, "max_drillholes": 2, "max_samples_per_drillhole": 2, "drillhole_limit_scope": "quadrant"},
        {"unexpected_limit": 1},
    ],
)
def test_staged_search_neighborhood_rejects_invalid_limits(bad_params: dict):
    with pytest.raises(ValidationError):
        SearchNeighborhoodData(
            name="bad",
            major=100.0,
            semi_major=75.0,
            minor=50.0,
            max_samples=24,
            **bad_params,
        )

    mcp = _build_staging_server()
    fake_ctx = _mock_staging_context()
    with (
        patch("evo_mcp.staging.objects.search_neighborhood.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
        patch("evo_mcp.staging.objects.variogram.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
        patch("evo_mcp.staging.objects.base.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
        patch("evo_mcp.tools.object_staging_tools.get_evo_context", new=AsyncMock(return_value=fake_ctx)),
    ):
        with pytest.raises((ToolError, ValidationError)):
            asyncio.run(
                mcp.call_tool(
                    "staging_create_object",
                    {
                        "object_type": "search_neighborhood",
                        "params": {
                            "object_name": "bad_sn",
                            "major": 100.0,
                            "semi_major": 75.0,
                            "minor": 50.0,
                            "max_samples": 24,
                            **bad_params,
                        },
                    },
                )
            )

        asyncio.run(
            mcp.call_tool(
                "staging_create_object",
                {
                    "object_type": "variogram",
                    "params": {
                        "object_name": "v1",
                        "sill": 1.0,
                        "nugget": 0.0,
                        "structures": [
                            {
                                "variogram_type": "spherical",
                                "contribution": 1.0,
                                "anisotropy": {
                                    "ellipsoid_ranges": {"major": 100.0, "semi_major": 75.0, "minor": 50.0},
                                },
                            }
                        ],
                    },
                },
            )
        )
        with pytest.raises((ToolError, ValidationError)):
            asyncio.run(
                mcp.call_tool(
                    "staging_invoke_interaction",
                    {
                        "object_name": "v1",
                        "interaction_name": "create_search_neighborhood",
                        "params": {
                            "object_name": "bad_derived_sn",
                            "max_samples": 24,
                            **bad_params,
                        },
                    },
                )
            )
