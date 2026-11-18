# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

import asyncio
from copy import deepcopy
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import jsonschema
import pytest
from evo.compute.client import JobClient
from evo.compute.tasks.common.results import TaskAttribute
from evo.compute.tasks.geostatistics.kriging import (
    KrigingResultModel,
    KrigingTargetResult,
    OrdinaryKriging,
    SimpleKriging,
)
from evo.objects import ObjectReference
from evo.objects.typed import Attribute, DownholeIntervals, PendingAttribute, PointSet, Regular3DGrid, Variogram
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.exceptions import ValidationError as InvalidArguments
from pydantic import ValidationError

from evo_mcp.tools import compute_tools
from evo_mcp.tools.compute_tools import KrigingBuildParams, register_compute_tools

HUB_URL = "https://hub.test.evo.bentley.com"
ORG_ID = "00000000-0000-0000-0000-000000000099"
WORKSPACE_ID = "00000000-0000-0000-0000-000000000088"
TARGET_ID = "00000000-0000-0000-0000-000000000001"
SOURCE_ID = "00000000-0000-0000-0000-000000000002"
VARIOGRAM_ID = "00000000-0000-0000-0000-000000000003"


def _object_url(object_id: str) -> str:
    return f"{HUB_URL}/geoscience-object/orgs/{ORG_ID}/workspaces/{WORKSPACE_ID}/objects/{object_id}"


def _mock_compute_objects(*, source_cls: type = DownholeIntervals) -> dict[str, Any]:
    source_obj = MagicMock(spec=source_cls)
    source_obj.metadata.url = ObjectReference(_object_url(SOURCE_ID))
    grade_attr = MagicMock(spec=Attribute)
    grade_attr.name = "grade"
    grade_attr.key = "grade-key"
    grade_attr.exists = True
    grade_attr._obj = source_obj
    grade_attr._context = SimpleNamespace(
        schema_path="intervals.attributes" if source_cls is DownholeIntervals else "locations.attributes"
    )
    source_attrs = MagicMock()
    source_attrs.__getitem__.side_effect = lambda name: (
        grade_attr if name == "grade" else PendingAttribute(source_attrs, name)
    )
    source_attrs.__iter__.side_effect = lambda: iter([grade_attr])
    source_obj.attributes = source_attrs

    target_obj = MagicMock(spec=Regular3DGrid)
    target_obj.metadata.url = ObjectReference(_object_url(TARGET_ID))
    target_parent = MagicMock()
    target_parent._obj = target_obj
    target_attrs = MagicMock()
    target_attrs.__getitem__.side_effect = lambda name: PendingAttribute(target_parent, name)
    target_obj.attributes = target_attrs

    variogram_obj = MagicMock(spec=Variogram)
    variogram_obj.metadata.url = ObjectReference(_object_url(VARIOGRAM_ID))

    return {
        SOURCE_ID: source_obj,
        TARGET_ID: target_obj,
        VARIOGRAM_ID: variogram_obj,
    }


def _build_compute_server() -> FastMCP:
    mcp = FastMCP("compute-test")
    register_compute_tools(mcp)
    return mcp


def _mock_job() -> AsyncMock:
    job = AsyncMock()
    job.wait_for_results.return_value = KrigingResultModel(
        message="Kriging completed",
        target=KrigingTargetResult(
            reference=_object_url(TARGET_ID),
            name="Target Grid",
            description=None,
            schema_id="/objects/regular-3d-grid/1.2.0/regular-3d-grid.schema.json",
            attribute=TaskAttribute(reference="cell_attributes[?key=='est-key']", name="estimate"),
        ),
    )
    return job


@pytest.fixture
def kriging_build_inputs() -> dict[str, Any]:
    return {
        "target_object_id": TARGET_ID,
        "target_attribute": "estimate",
        "point_set_object_id": SOURCE_ID,
        "point_set_attribute": "grade",
        "variogram_object_id": VARIOGRAM_ID,
        "neighborhood": {
            "ellipsoid": {"ranges": {"major": 100, "semi_major": 75, "minor": 50}},
            "max_samples": 20,
        },
    }


def test_kriging_build_parameters_use_canonical_discretization(kriging_build_inputs):
    parameters = KrigingBuildParams(
        **kriging_build_inputs,
        block_discretization={"nx": 2, "ny": 3, "nz": 4},
    )

    payload = parameters.model_dump(mode="json")
    assert payload["block_discretization"] == {"nx": 2, "ny": 3, "nz": 4}
    assert "block_discretisation" not in payload


def test_kriging_build_schema_uses_canonical_discretization_and_kriging_names():
    properties = KrigingBuildParams.model_json_schema()["properties"]
    assert "block_discretization" in properties
    assert "block_discretisation" not in properties
    assert "neighborhood" in properties
    assert "search" not in properties
    assert "kriging_method" in properties
    assert "method" not in properties


def test_tool_validation_schemas_accept_ellipsoid_ranges_alias_and_optional_rotation(kriging_build_inputs):
    mcp = _build_compute_server()
    tool_schemas = {tool.name: tool.parameters for tool in asyncio.run(mcp.list_tools())}

    build_validator = jsonschema.Draft202012Validator(tool_schemas["kriging_build_parameters"])
    assert build_validator.is_valid({"workspace_id": WORKSPACE_ID, "params": kriging_build_inputs})
    assert build_validator.is_valid(
        {
            "workspace_id": WORKSPACE_ID,
            "params": {
                **kriging_build_inputs,
                "neighborhood": {
                    "ellipsoid": {"ellipsoid_ranges": {"major": 100, "semi_major": 75, "minor": 50}},
                    "max_samples": 20,
                },
            },
        }
    )
    assert not build_validator.is_valid(
        {
            "workspace_id": WORKSPACE_ID,
            "params": {
                **kriging_build_inputs,
                "neighborhood": {
                    "ellipsoid": {"rotation": {"dip_azimuth": 45}},
                    "max_samples": 20,
                },
            },
        }
    )
    assert not build_validator.is_valid(
        {
            "workspace_id": WORKSPACE_ID,
            "params": {
                **kriging_build_inputs,
                "neighborhood": {
                    "ellipsoid": {
                        "ranges": {"major": 100, "semi_major": 75, "minor": 50},
                        "_rotation": {"dip_azimuth": 45},
                    },
                    "max_samples": 20,
                },
            },
        }
    )

    run_validator = jsonschema.Draft202012Validator(tool_schemas["kriging_run"])
    base_scenario = {
        "source": {"object": _object_url(SOURCE_ID), "attribute": "intervals.attributes[?key=='grade-key']"},
        "target": {"object": _object_url(TARGET_ID), "attribute": {"operation": "create", "name": "estimate"}},
        "variogram": _object_url(VARIOGRAM_ID),
        "neighborhood": {
            "ellipsoid": {"ranges": {"major": 100.0, "semi_major": 75.0, "minor": 50.0}},
            "max_samples": 20,
        },
    }
    assert run_validator.is_valid({"workspace_id": WORKSPACE_ID, "scenarios": [base_scenario]})

    serialization_ellipsoid = KrigingBuildParams.model_json_schema(mode="serialization")["$defs"]["SearchNeighborhood"][
        "properties"
    ]["ellipsoid"]
    assert serialization_ellipsoid["required"] == ["ellipsoid_ranges", "rotation"]
    assert "ranges" not in serialization_ellipsoid["properties"]


@pytest.mark.parametrize("include_canonical", [False, True])
def test_kriging_build_rejects_legacy_discretisation(kriging_build_inputs, include_canonical):
    legacy_inputs = {**kriging_build_inputs, "block_discretisation": {"nx": 2, "ny": 3, "nz": 4}}
    if include_canonical:
        legacy_inputs["block_discretization"] = {"nx": 2, "ny": 3, "nz": 4}

    with pytest.raises(ValidationError, match="block_discretisation"):
        KrigingBuildParams(**legacy_inputs)


def test_kriging_build_params_accepts_canonical_and_legacy_aliases(kriging_build_inputs):
    default_params = KrigingBuildParams(**kriging_build_inputs)
    assert isinstance(default_params.kriging_method, OrdinaryKriging)
    assert default_params.method is default_params.kriging_method
    assert default_params.search is default_params.neighborhood

    legacy_inputs = {k: v for k, v in kriging_build_inputs.items() if k != "neighborhood"}
    legacy_inputs["search"] = {
        "ellipsoid": {
            "ellipsoid_ranges": {"major": 200, "semi_major": 150, "minor": 100},
            "rotation": {"dip_azimuth": 45, "dip": 30, "pitch": 15},
        },
        "max_samples": 24,
        "max_samples_per_drillhole": 2,
        "max_drillholes_per_estimate": 6,
        "min_drillholes_per_estimate": 2,
        "drillhole_limit_scope": "quadrant",
    }
    legacy_inputs["method"] = {"type": "simple", "mean": 1.25}

    parsed = KrigingBuildParams(**legacy_inputs)
    assert isinstance(parsed.kriging_method, SimpleKriging)
    assert parsed.method.mean == 1.25
    assert parsed.neighborhood.max_drillholes == 6
    assert parsed.neighborhood.max_drillholes_per_estimate == 6
    assert parsed.neighborhood.min_drillholes == 2
    assert parsed.neighborhood.drillhole_limit_scope == "quadrant"

    dumped = parsed.model_dump(mode="json")
    assert "neighborhood" in dumped and "search" not in dumped
    assert "kriging_method" in dumped and "method" not in dumped
    assert dumped["neighborhood"]["max_drillholes"] == 6
    assert dumped["neighborhood"]["min_drillholes"] == 2
    assert dumped["neighborhood"]["drillhole_limit_scope"] == "quadrant"


@pytest.mark.parametrize(
    ("neighborhood_key", "method_key", "max_dh_key", "min_dh_key", "scope"),
    [
        ("neighborhood", "kriging_method", "max_drillholes", "min_drillholes", "global"),
        ("search", "method", "max_drillholes_per_estimate", "min_drillholes_per_estimate", "quadrant"),
        ("neighborhood", "kriging_method", "max_drillholes", "min_drillholes", "octant"),
    ],
)
def test_kriging_build_to_run_round_trip_with_downhole_intervals(
    neighborhood_key: str,
    method_key: str,
    max_dh_key: str,
    min_dh_key: str,
    scope: str,
):
    mcp = _build_compute_server()
    objects = _mock_compute_objects(source_cls=DownholeIntervals)
    env = SimpleNamespace(org_id=ORG_ID, workspace_id=WORKSPACE_ID, hub_url=HUB_URL)
    evo_ctx = SimpleNamespace(connector=MagicMock())

    params: dict[str, Any] = {
        "target_object_id": TARGET_ID,
        "target_attribute": "estimate",
        "point_set_object_id": SOURCE_ID,
        "point_set_attribute": "grade",
        "variogram_object_id": VARIOGRAM_ID,
        neighborhood_key: {
            "ellipsoid": {
                "ranges": {"major": 200.0, "semi_major": 150.0, "minor": 100.0},
                "rotation": {"dip_azimuth": 45.0, "dip": 30.0, "pitch": 15.0},
            },
            "max_samples": 24,
            "min_samples": 4,
            "max_empty_octants": 4,
            "max_samples_per_octant": 4,
            "max_samples_per_drillhole": 2,
            max_dh_key: 6,
            min_dh_key: 2,
            "drillhole_limit_scope": scope,
        },
        method_key: {"type": "simple", "mean": 2.5},
        "source_filter": {
            "where": {"type": "condition", "attribute": "grade", "operator": "greater_than", "threshold": 0.1}
        },
        "target_filter": {"where": {"type": "condition", "attribute": "domain", "operator": "in", "values": ["LMS1"]}},
        "block_discretization": {"nx": 2, "ny": 2, "nz": 2},
    }

    with (
        patch.object(compute_tools, "get_workspace_environment", new=AsyncMock(return_value=env)),
        patch.object(compute_tools, "get_evo_context", new=AsyncMock(return_value=evo_ctx)),
        patch.object(compute_tools.StaticContext, "from_environment", return_value=MagicMock()),
        patch.object(
            compute_tools,
            "object_from_uuid",
            new=AsyncMock(side_effect=lambda _ctx, oid: objects[oid]),
        ),
        patch.object(JobClient, "submit", new=AsyncMock(return_value=_mock_job())) as mock_submit,
        patch.object(compute_tools, "format_task_result_with_target", return_value="<div>ok</div>"),
    ):
        built = asyncio.run(
            mcp.call_tool("kriging_build_parameters", {"workspace_id": WORKSPACE_ID, "params": params})
        ).structured_content

        assert "neighborhood" in built and "search" not in built
        assert "kriging_method" in built and "method" not in built
        assert built["kriging_method"] == {"type": "simple", "mean": 2.5}
        assert built["neighborhood"]["ellipsoid"] == {
            "ellipsoid_ranges": {"major": 200.0, "semi_major": 150.0, "minor": 100.0},
            "rotation": {"dip_azimuth": 45.0, "dip": 30.0, "pitch": 15.0},
        }
        assert built["neighborhood"]["max_drillholes"] == 6
        assert built["neighborhood"]["min_drillholes"] == 2
        if scope == "global":
            assert "drillhole_limit_scope" not in built["neighborhood"]
        else:
            assert built["neighborhood"]["drillhole_limit_scope"] == scope

        run_result = asyncio.run(
            mcp.call_tool("kriging_run", {"workspace_id": WORKSPACE_ID, "scenarios": [deepcopy(built)]})
        ).structured_content

    assert run_result["status"] == "success"
    assert run_result["scenarios_completed"] == 1
    submitted = mock_submit.call_args.kwargs["parameters"]
    assert submitted["neighborhood"] == built["neighborhood"]
    assert submitted["kriging_method"] == {"type": "simple", "mean": 2.5}
    assert submitted["source"]["filter"]["where"]["threshold"] == 0.1
    assert submitted["target"]["filter"]["where"]["values"] == ["LMS1"]
    assert submitted["block_discretization"] == {"nx": 2, "ny": 2, "nz": 2}


def test_kriging_build_parameters_allows_pointset_without_active_drillhole_limits(kriging_build_inputs):
    mcp = _build_compute_server()
    objects = _mock_compute_objects(source_cls=PointSet)
    env = SimpleNamespace(org_id=ORG_ID, workspace_id=WORKSPACE_ID, hub_url=HUB_URL)
    evo_ctx = SimpleNamespace(connector=MagicMock())

    inputs = deepcopy(kriging_build_inputs)
    inputs["neighborhood"].update(
        {
            "max_samples_per_octant": 4,
            "min_drillholes": 0,
            "drillhole_limit_scope": "global",
        }
    )

    with (
        patch.object(compute_tools, "get_workspace_environment", new=AsyncMock(return_value=env)),
        patch.object(compute_tools, "get_evo_context", new=AsyncMock(return_value=evo_ctx)),
        patch.object(compute_tools.StaticContext, "from_environment", return_value=MagicMock()),
        patch.object(
            compute_tools,
            "object_from_uuid",
            new=AsyncMock(side_effect=lambda _ctx, oid: objects[oid]),
        ),
    ):
        built = asyncio.run(
            mcp.call_tool("kriging_build_parameters", {"workspace_id": WORKSPACE_ID, "params": inputs})
        ).structured_content

    assert "min_drillholes" not in built["neighborhood"]
    assert "drillhole_limit_scope" not in built["neighborhood"]
    assert built["neighborhood"]["max_samples_per_octant"] == 4


@pytest.mark.parametrize(
    "drillhole_limits",
    [
        {"max_samples_per_drillhole": 2},
        {"max_drillholes": 4},
        {"max_drillholes_per_estimate": 4},
        {"min_drillholes": 2},
        {"min_drillholes_per_estimate": 2},
        {"max_samples_per_drillhole": 2, "drillhole_limit_scope": "quadrant"},
        {"max_samples_per_drillhole": 2, "drillhole_limit_scope": "octant"},
    ],
)
def test_kriging_build_parameters_rejects_drillhole_limits_on_pointset(
    kriging_build_inputs: dict[str, Any],
    drillhole_limits: dict[str, Any],
):
    mcp = _build_compute_server()
    objects = _mock_compute_objects(source_cls=PointSet)
    env = SimpleNamespace(org_id=ORG_ID, workspace_id=WORKSPACE_ID, hub_url=HUB_URL)
    evo_ctx = SimpleNamespace(connector=MagicMock())

    inputs = deepcopy(kriging_build_inputs)
    inputs["neighborhood"].update(drillhole_limits)

    with (
        patch.object(compute_tools, "get_workspace_environment", new=AsyncMock(return_value=env)),
        patch.object(compute_tools, "get_evo_context", new=AsyncMock(return_value=evo_ctx)),
        patch.object(compute_tools.StaticContext, "from_environment", return_value=MagicMock()),
        patch.object(
            compute_tools,
            "object_from_uuid",
            new=AsyncMock(side_effect=lambda _ctx, oid: objects[oid]),
        ),
        pytest.raises(ToolError, match=r"DownholeIntervals.*PointSet"),
    ):
        asyncio.run(mcp.call_tool("kriging_build_parameters", {"workspace_id": WORKSPACE_ID, "params": inputs}))


@pytest.mark.parametrize("scope", ["quadrant", "octant"])
def test_non_global_drillhole_limit_scope_requires_max_samples_per_drillhole(
    kriging_build_inputs: dict[str, Any],
    scope: str,
):
    inputs = deepcopy(kriging_build_inputs)
    inputs["neighborhood"]["drillhole_limit_scope"] = scope

    with pytest.raises(ValidationError, match="requires max_samples_per_drillhole"):
        KrigingBuildParams(**inputs)


@pytest.mark.parametrize(
    "conflicting_patch",
    [
        {
            "search": {
                "ellipsoid": {"ranges": {"major": 100, "semi_major": 75, "minor": 50}},
                "max_samples": 12,
            }
        },
        {
            "kriging_method": {"type": "ordinary"},
            "method": {"type": "simple", "mean": 5.0},
        },
        {
            "neighborhood": {
                "ellipsoid": {"ranges": {"major": 100, "semi_major": 75, "minor": 50}},
                "max_samples": 20,
                "max_drillholes": 6,
                "max_drillholes_per_estimate": 4,
            }
        },
        {
            "neighborhood": {
                "ellipsoid": {"ranges": {"major": 100, "semi_major": 75, "minor": 50}},
                "max_samples": 20,
                "min_drillholes": 2,
                "min_drillholes_per_estimate": 3,
            }
        },
    ],
)
def test_conflicting_aliases_are_rejected(
    kriging_build_inputs: dict[str, Any],
    conflicting_patch: dict[str, Any],
):
    inputs = {**deepcopy(kriging_build_inputs), **conflicting_patch}
    with pytest.raises(ValidationError, match="Conflicting values"):
        KrigingBuildParams(**inputs)


@pytest.mark.parametrize(
    "invalid_limits",
    [
        {"max_samples": 20, "min_samples": 9, "max_samples_per_octant": 1},
        {"max_samples": 20, "min_samples": 7, "max_drillholes": 3, "max_samples_per_drillhole": 2},
        {
            "max_samples": 24,
            "min_samples": 17,
            "max_drillholes": 2,
            "max_samples_per_drillhole": 2,
            "drillhole_limit_scope": "quadrant",
        },
        {
            "max_samples": 40,
            "min_samples": 33,
            "max_drillholes": 2,
            "max_samples_per_drillhole": 2,
            "drillhole_limit_scope": "octant",
        },
        {"max_samples": 20, "min_drillholes": 5, "max_drillholes": 4},
        {"max_samples": 20, "max_empty_octants": 0, "max_drillholes": 2, "max_samples_per_drillhole": 2},
    ],
)
def test_contradictory_sector_and_drillhole_ceilings_are_rejected(
    kriging_build_inputs: dict[str, Any],
    invalid_limits: dict[str, Any],
):
    inputs = deepcopy(kriging_build_inputs)
    inputs["neighborhood"].update(invalid_limits)

    with pytest.raises(ValidationError):
        KrigingBuildParams(**inputs)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.__setitem__("unexpected_top", 1),
        lambda d: d["neighborhood"].__setitem__("unexpected_neighborhood", 1),
        lambda d: d["neighborhood"]["ellipsoid"].__setitem__("_rotation", {"dip_azimuth": 10, "dip": 0, "pitch": 0}),
        lambda d: d["neighborhood"]["ellipsoid"].__setitem__("unexpected_ellipsoid", 1),
        lambda d: d["neighborhood"]["ellipsoid"]["ranges"].__setitem__("unexpected_range", 1),
        lambda d: d["neighborhood"]["ellipsoid"].__setitem__(
            "rotation", {"dip_azimuth": 10, "dip": 0, "pitch": 0, "unexpected_rot": 1}
        ),
        lambda d: d.__setitem__("kriging_method", {"type": "ordinary", "unexpected_method": 1}),
        lambda d: d.__setitem__("block_discretization", {"nx": 2, "ny": 2, "nz": 2, "unexpected_bd": 1}),
        lambda d: d.__setitem__(
            "source_filter",
            {
                "where": {
                    "type": "condition",
                    "attribute": "grade",
                    "operator": "greater_than",
                    "threshold": 0.0,
                    "extra": 1,
                }
            },
        ),
    ],
)
def test_unknown_fields_are_rejected_at_every_nesting_level_in_build(
    kriging_build_inputs: dict[str, Any],
    mutate: Any,
):
    inputs = deepcopy(kriging_build_inputs)
    mutate(inputs)
    with pytest.raises(ValidationError):
        KrigingBuildParams(**inputs)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda s: s.__setitem__("unexpected_top", 1),
        lambda s: s["neighborhood"].__setitem__("unexpected_neighborhood", 1),
        lambda s: s["neighborhood"]["ellipsoid"].__setitem__("_rotation", {"dip_azimuth": 10, "dip": 0, "pitch": 0}),
        lambda s: s["kriging_method"].__setitem__("unexpected_method", 1),
        lambda s: s["source"].__setitem__("unexpected_source", 1),
        lambda s: s["target"]["attribute"].__setitem__("unexpected_attr", 1),
    ],
)
def test_unknown_fields_are_rejected_at_every_nesting_level_in_run(mutate: Any):
    mcp = _build_compute_server()
    scenario: dict[str, Any] = {
        "source": {"object": _object_url(SOURCE_ID), "attribute": "intervals.attributes[?key=='grade-key']"},
        "target": {"object": _object_url(TARGET_ID), "attribute": {"operation": "create", "name": "estimate"}},
        "variogram": _object_url(VARIOGRAM_ID),
        "neighborhood": {
            "ellipsoid": {
                "ellipsoid_ranges": {"major": 100.0, "semi_major": 75.0, "minor": 50.0},
                "rotation": {"dip_azimuth": 0.0, "dip": 0.0, "pitch": 0.0},
            },
            "max_samples": 20,
        },
        "kriging_method": {"type": "ordinary"},
    }
    mutate(scenario)
    with pytest.raises((InvalidArguments, ToolError)):
        asyncio.run(mcp.call_tool("kriging_run", {"workspace_id": WORKSPACE_ID, "scenarios": [scenario]}))
