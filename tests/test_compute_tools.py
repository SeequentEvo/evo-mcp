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
from evo.compute.tasks import run as run_sdk_compute
from evo.compute.tasks.common import Filter
from evo.compute.tasks.common.results import TaskAttribute
from evo.compute.tasks.geostatistics.idw import IDWParameters
from evo.compute.tasks.geostatistics.kriging import (
    KrigingParameters,
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
from evo_mcp.tools.compute_tools import register_compute_tools
from evo_mcp.utils import compute_helpers
from evo_mcp.utils.compute_params import IDWBuildParams, KrigingBuildParams
from evo_mcp.utils.tool_support import MCPFeedback


def test_compute_build_parameter_imports_remain_compatible():
    assert compute_tools.IDWBuildParams is IDWBuildParams
    assert compute_tools.KrigingBuildParams is KrigingBuildParams


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
    target_obj.as_dict.return_value = {}
    domain_attr = MagicMock(spec=Attribute)
    domain_attr.name = "domain"
    domain_attr.key = "domain-key"
    domain_attr.exists = True
    domain_attr._obj = target_obj
    domain_attr._context = SimpleNamespace(schema_path="cell_attributes")
    target_parent = MagicMock()
    target_parent._obj = target_obj
    target_attrs = MagicMock()
    target_attrs.__getitem__.side_effect = lambda name: (
        domain_attr if name == "domain" else PendingAttribute(target_parent, name)
    )
    target_attrs.__iter__.side_effect = lambda: iter([domain_attr])
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
        patch.object(compute_helpers, "get_workspace_environment", new=AsyncMock(return_value=env)),
        patch.object(compute_helpers, "get_evo_context", new=AsyncMock(return_value=evo_ctx)),
        patch.object(compute_helpers.StaticContext, "from_environment", return_value=MagicMock()),
        patch.object(
            compute_helpers,
            "object_from_uuid",
            new=AsyncMock(side_effect=lambda _ctx, oid: objects[oid]),
        ),
        patch.object(JobClient, "submit", new=AsyncMock(return_value=_mock_job())) as mock_submit,
        patch.object(compute_helpers, "format_task_result_with_target", return_value="<div>ok</div>"),
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
        patch.object(compute_helpers, "get_workspace_environment", new=AsyncMock(return_value=env)),
        patch.object(compute_helpers, "get_evo_context", new=AsyncMock(return_value=evo_ctx)),
        patch.object(compute_helpers.StaticContext, "from_environment", return_value=MagicMock()),
        patch.object(
            compute_helpers,
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
        patch.object(compute_helpers, "get_workspace_environment", new=AsyncMock(return_value=env)),
        patch.object(compute_helpers, "get_evo_context", new=AsyncMock(return_value=evo_ctx)),
        patch.object(compute_helpers.StaticContext, "from_environment", return_value=MagicMock()),
        patch.object(
            compute_helpers,
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


@pytest.fixture
def compute_server(monkeypatch, kriging_build_inputs):
    workspace_id = "00000000-0000-0000-0000-000000000004"
    org_id = "00000000-0000-0000-0000-000000000005"
    environment = SimpleNamespace(org_id=org_id, workspace_id=workspace_id, hub_url="https://example.test")

    def object_url(object_id):
        return f"https://example.test/geoscience-object/orgs/{org_id}/workspaces/{workspace_id}/objects/{object_id}"

    source = MagicMock(spec=PointSet)
    source.metadata.url = object_url(kriging_build_inputs["point_set_object_id"])
    source_attribute = MagicMock(spec=Attribute)
    source_attribute.name = "grade"
    source_attribute.key = "grade-key"
    source_attribute.exists = True
    source_attribute._context = SimpleNamespace(schema_path="locations.attributes")
    source.attributes = {"grade": source_attribute}

    target = MagicMock(spec=Regular3DGrid)
    target.metadata.url = object_url(kriging_build_inputs["target_object_id"])
    target.as_dict.return_value = {}
    target_attribute = MagicMock(spec=PendingAttribute)
    target_attribute.name = "estimate"
    target_attribute.exists = False
    target_attribute._obj = target
    target_domain = MagicMock(spec=Attribute)
    target_domain.name = "domain"
    target_domain.key = "domain-key"
    target_domain.exists = True
    target_domain._context = SimpleNamespace(schema_path="cell_attributes")
    target.attributes = {"estimate": target_attribute, "domain": target_domain}

    variogram = MagicMock(spec=Variogram)
    variogram.metadata.url = object_url(kriging_build_inputs["variogram_object_id"])
    objects = {
        kriging_build_inputs["point_set_object_id"]: source,
        kriging_build_inputs["target_object_id"]: target,
        kriging_build_inputs["variogram_object_id"]: variogram,
    }
    resolve = AsyncMock(side_effect=lambda context, object_id: objects[object_id])
    run = AsyncMock(return_value=[])
    context = object()
    monkeypatch.setattr(compute_helpers, "get_workspace_environment", AsyncMock(return_value=environment))
    monkeypatch.setattr(compute_helpers, "get_evo_context", AsyncMock(return_value=SimpleNamespace(connector=object())))
    monkeypatch.setattr(compute_helpers.StaticContext, "from_environment", MagicMock(return_value=context))
    monkeypatch.setattr(compute_helpers, "object_from_uuid", resolve)
    monkeypatch.setattr(compute_helpers, "run_compute", run)
    monkeypatch.setattr(compute_helpers, "format_task_result_with_target", lambda result: "<div>Result</div>")
    server = FastMCP("compute-test")
    compute_tools.register_compute_tools(server)
    return SimpleNamespace(
        server=server,
        workspace_id=workspace_id,
        context=context,
        source=source,
        target=target,
        objects=objects,
        resolve=resolve,
        run=run,
    )


@pytest.fixture(params=["kriging", "idw"])
def estimation_case(request, kriging_build_inputs, neighborhood_build_inputs):
    models = {"kriging": KrigingParameters, "idw": IDWParameters}
    return SimpleNamespace(
        name=request.param,
        inputs=kriging_build_inputs if request.param == "kriging" else neighborhood_build_inputs,
        model=models[request.param],
    )


@pytest.fixture
def neighborhood_build_inputs(kriging_build_inputs):
    return {key: value for key, value in kriging_build_inputs.items() if key != "variogram_object_id"}


def _search_dict(inputs: dict[str, Any]) -> dict[str, Any]:
    return inputs["neighborhood"] if "neighborhood" in inputs else inputs["search"]


def _with_search(inputs: dict[str, Any], search_value: dict[str, Any]) -> dict[str, Any]:
    cleaned = {k: v for k, v in inputs.items() if k not in ("neighborhood", "search")}
    cleaned["neighborhood"] = search_value
    return cleaned


@pytest.mark.parametrize("power", [0, -1, float("inf"), float("nan")])
def test_idw_rejects_invalid_power(neighborhood_build_inputs, power):
    with pytest.raises(ValidationError, match="power"):
        IDWBuildParams(**neighborhood_build_inputs, power=power)


@pytest.mark.parametrize("model", [IDWBuildParams])
@pytest.mark.parametrize("limits", [{"max_samples": 0}, {"min_samples": 0}, {"min_samples": -1}, {"min_samples": 21}])
def test_neighborhood_estimation_rejects_invalid_sample_limits(neighborhood_build_inputs, model, limits):
    base_search = _search_dict(neighborhood_build_inputs)
    inputs = _with_search(neighborhood_build_inputs, {**base_search, **limits})
    with pytest.raises(ValidationError, match="min_samples|max_samples"):
        model(**inputs)


@pytest.mark.asyncio
async def test_idw_build_payload_round_trip(compute_server, neighborhood_build_inputs):
    result = await compute_server.server.call_tool(
        "idw_build_parameters",
        {"workspace_id": compute_server.workspace_id, "params": neighborhood_build_inputs},
    )
    payload = result.structured_content
    scenario = IDWParameters.model_validate(payload)
    assert scenario.power == 2.0
    assert scenario.target.attribute.name == "estimate"
    assert payload["neighborhood"]["ellipsoid"]["ellipsoid_ranges"]["major"] == 100
    assert compute_server.resolve.await_count == 2
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("drillhole_limits", [{"max_samples_per_drillhole": 2}, {"max_drillholes": 4}])
async def test_idw_rejects_drillhole_limits_on_pointset(compute_server, neighborhood_build_inputs, drillhole_limits):
    base_search = _search_dict(neighborhood_build_inputs)
    inputs = _with_search(neighborhood_build_inputs, {**base_search, **drillhole_limits})
    with pytest.raises(ToolError, match=r"DownholeIntervals.*PointSet"):
        await compute_server.server.call_tool(
            "idw_build_parameters",
            {"workspace_id": compute_server.workspace_id, "params": inputs},
        )
    compute_server.run.assert_not_awaited()


def estimation_result(compute_server, attribute="estimate"):
    return SimpleNamespace(
        message="Estimation complete",
        target_name="Target grid",
        target_reference=str(compute_server.target.metadata.url),
        attribute_name=attribute,
        schema="/objects/regular-3d-grid/1.0.0/regular-3d-grid.schema.json",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["kriging", "idw"])
async def test_compute_uses_sdk_dispatch(
    compute_server, kriging_build_inputs, neighborhood_build_inputs, monkeypatch, name
):
    inputs = {"kriging": kriging_build_inputs, "idw": neighborhood_build_inputs}[name]
    rotation = {"dip_azimuth": 45.0, "dip": 30.0, "pitch": 10.0}
    condition = {"where": {"type": "condition", "attribute": "grade", "operator": "greater_than", "threshold": 0.0}}
    base_search = _search_dict(inputs)
    inputs = {
        **_with_search(
            inputs,
            {**base_search, "ellipsoid": {**base_search["ellipsoid"], "rotation": rotation}},
        ),
        "source_filter": condition,
        "target_filter": {"where": {**condition["where"], "attribute": "domain"}},
    }
    context = MagicMock()
    monkeypatch.setattr(compute_helpers.StaticContext, "from_environment", MagicMock(return_value=context))
    built = await compute_server.server.call_tool(
        f"{name}_build_parameters", {"workspace_id": compute_server.workspace_id, "params": inputs}
    )
    target = {
        "reference": str(compute_server.target.metadata.url),
        "name": "Target grid",
        "schema_id": "/objects/regular-3d-grid/1.0.0/regular-3d-grid.schema.json",
    }
    attribute = {"reference": "cell_attributes[?name=='estimate']", "name": "estimate"}
    target["attribute"] = attribute
    response = {"message": "Estimation complete", "target": target}
    job = SimpleNamespace(wait_for_results=AsyncMock())

    async def submit(*, result_type, **kwargs):
        job.wait_for_results.return_value = result_type.model_validate(response)
        return job

    submit_job = AsyncMock(side_effect=submit)
    monkeypatch.setattr(JobClient, "submit", submit_job)
    monkeypatch.setattr(compute_helpers, "run_compute", run_sdk_compute)
    result = await compute_server.server.call_tool(
        f"{name}_run", {"workspace_id": compute_server.workspace_id, "scenarios": [built.structured_content]}
    )
    request = submit_job.call_args.kwargs
    assert request["connector"] is context.get_connector.return_value
    assert request["org_id"] is context.get_org_id.return_value
    assert request["topic"] == "geostatistics"
    assert request["task"] == name
    assert request["preview"] is True
    payload = request["parameters"]
    assert payload["neighborhood"]["ellipsoid"]["rotation"] == rotation
    assert payload["neighborhood"]["ellipsoid"]["ellipsoid_ranges"]["major"] == 100
    source_condition = {"where": {**condition["where"], "attribute": "locations.attributes[?key=='grade-key']"}}
    target_condition = {"where": {**condition["where"], "attribute": "cell_attributes[?key=='domain-key']"}}
    assert payload["source"]["filter"] == Filter.model_validate(source_condition).model_dump()
    assert payload["target"]["filter"] == Filter.model_validate(target_condition).model_dump()
    assert payload["target"]["attribute"]["operation"] == "create"
    job.wait_for_results.assert_awaited_once()
    assert result.structured_content["scenarios_completed"] == 1
    assert result.structured_content["results"][0]["target"]["reference"] == target["reference"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["kriging", "idw"])
@pytest.mark.parametrize("boundary", ["build", "run"])
async def test_compute_rejects_zero_minimum_samples(
    compute_server, kriging_build_inputs, neighborhood_build_inputs, name, boundary
):
    inputs = {"kriging": kriging_build_inputs, "idw": neighborhood_build_inputs}[name]
    arguments = {"workspace_id": compute_server.workspace_id}
    if boundary == "build":
        base_search = _search_dict(inputs)
        arguments["params"] = _with_search(inputs, {**base_search, "min_samples": 0})
        tool = f"{name}_build_parameters"
    else:
        built = await compute_server.server.call_tool(
            f"{name}_build_parameters", {"workspace_id": compute_server.workspace_id, "params": inputs}
        )
        scenario = built.structured_content
        scenario["neighborhood"]["min_samples"] = 0
        arguments["scenarios"] = [scenario]
        tool = f"{name}_run"
    with pytest.raises(InvalidArguments, match="min_samples"):
        await compute_server.server.call_tool(tool, arguments)
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimation_filters_survive_build_and_run(compute_server, estimation_case):
    inputs = {
        **estimation_case.inputs,
        "source_filter": {
            "where": {"type": "condition", "attribute": "grade", "operator": "greater_than", "threshold": 0.0}
        },
        "target_filter": {"where": {"type": "condition", "attribute": "domain", "operator": "in", "values": ["ore"]}},
    }
    built = await compute_server.server.call_tool(
        f"{estimation_case.name}_build_parameters",
        {"workspace_id": compute_server.workspace_id, "params": inputs},
    )
    payload = built.structured_content
    assert payload["source_filter"]["where"]["attribute"] == "locations.attributes[?key=='grade-key']"
    assert payload["target_filter"]["where"]["attribute"] == "cell_attributes[?key=='domain-key']"
    assert payload["target_filter"]["where"]["values"] == ["ore"]
    assert "filter" not in payload["source"]
    assert "filter" not in payload["target"]
    compute_server.run.return_value = [estimation_result(compute_server)]

    result = await compute_server.server.call_tool(
        f"{estimation_case.name}_run",
        {"workspace_id": compute_server.workspace_id, "scenarios": [payload]},
    )
    context, scenarios = compute_server.run.call_args.args
    assert context is compute_server.context
    assert isinstance(scenarios[0], estimation_case.model)
    assert scenarios[0].source_filter.where.attribute == "locations.attributes[?key=='grade-key']"
    assert scenarios[0].target_filter.where.values == ["ore"]
    assert compute_server.run.call_args.kwargs["preview"] is True
    assert isinstance(compute_server.run.call_args.kwargs["fb"], MCPFeedback)
    content = result.structured_content
    assert content["scenarios_completed"] == 1
    output = content["results"][0]
    assert output["target"]["attribute"] == {"operation": "create", "name": "estimate", "requested": "estimate"}
    assert output["target"]["locator"]["workspace_id"] == compute_server.workspace_id
    assert output["presentation"]["viewer_url"]
    assert output["presentation"]["portal_url"]


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["kriging", "idw"])
async def test_compute_resolves_nested_filter_names(
    compute_server, kriging_build_inputs, neighborhood_build_inputs, name
):
    inputs = {"kriging": kriging_build_inputs, "idw": neighborhood_build_inputs}[name]
    condition = {"type": "condition", "attribute": "grade", "operator": "greater_than", "threshold": 0.0}
    expression = "locations.attributes[?name=='grade']"
    source_filter = {
        "where": {
            "type": "all_of",
            "filters": [condition, {"type": "any_of", "filters": [{**condition, "attribute": expression}]}],
        }
    }
    built = await compute_server.server.call_tool(
        f"{name}_build_parameters",
        {"workspace_id": compute_server.workspace_id, "params": {**inputs, "source_filter": source_filter}},
    )
    filters = built.structured_content["source_filter"]["where"]["filters"]
    assert filters[0]["attribute"] == "locations.attributes[?key=='grade-key']"
    assert filters[1]["filters"][0]["attribute"] == expression
    assert source_filter["where"]["filters"][0]["attribute"] == "grade"


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["kriging", "idw"])
@pytest.mark.parametrize(
    "field, available",
    [("source_filter", "grade"), ("target_filter", "domain")],
)
async def test_compute_rejects_missing_filter_attribute(
    compute_server, kriging_build_inputs, neighborhood_build_inputs, name, field, available
):
    inputs = {"kriging": kriging_build_inputs, "idw": neighborhood_build_inputs}[name]
    missing_filter = {
        "where": {
            "type": "all_of",
            "filters": [{"type": "condition", "attribute": "missing", "operator": "greater_than", "threshold": 0.0}],
        }
    }
    with pytest.raises(ToolError, match=rf"{field} attribute 'missing' does not exist.*{available}"):
        await compute_server.server.call_tool(
            f"{name}_build_parameters",
            {"workspace_id": compute_server.workspace_id, "params": {**inputs, field: missing_filter}},
        )
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimation_preserves_scenario_order(compute_server, estimation_case):
    built = await compute_server.server.call_tool(
        f"{estimation_case.name}_build_parameters",
        {"workspace_id": compute_server.workspace_id, "params": estimation_case.inputs},
    )
    first = built.structured_content
    second = deepcopy(first)
    second["target"]["attribute"]["name"] = "estimate_two"
    compute_server.run.return_value = [
        estimation_result(compute_server),
        estimation_result(compute_server, "estimate_two"),
    ]
    result = await compute_server.server.call_tool(
        f"{estimation_case.name}_run",
        {"workspace_id": compute_server.workspace_id, "scenarios": [first, second]},
    )
    assert [item["target"]["attribute"]["name"] for item in result.structured_content["results"]] == [
        "estimate",
        "estimate_two",
    ]


@pytest.mark.asyncio
async def test_estimation_updates_existing_target_attribute(compute_server, estimation_case):
    attribute = MagicMock(spec=Attribute)
    attribute.name = "estimate"
    attribute.key = "estimate-key"
    attribute.exists = True
    attribute._obj = compute_server.target
    attribute._context = SimpleNamespace(schema_path="cell_attributes")
    compute_server.target.attributes["estimate"] = attribute
    built = await compute_server.server.call_tool(
        f"{estimation_case.name}_build_parameters",
        {"workspace_id": compute_server.workspace_id, "params": estimation_case.inputs},
    )
    assert built.structured_content["target"]["attribute"]["operation"] == "update"
    compute_server.run.return_value = [estimation_result(compute_server)]
    result = await compute_server.server.call_tool(
        f"{estimation_case.name}_run",
        {"workspace_id": compute_server.workspace_id, "scenarios": [built.structured_content]},
    )
    output = result.structured_content["results"][0]["target"]["attribute"]
    assert output == {"operation": "update", "name": "estimate", "requested": "estimate"}


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["point_set_attribute", "target_attribute"])
@pytest.mark.parametrize("value", ["", "   "])
async def test_estimation_rejects_empty_attribute_names(compute_server, estimation_case, field, value):
    with pytest.raises(ToolError, match=f"{field} must be a non-empty string"):
        await compute_server.server.call_tool(
            f"{estimation_case.name}_build_parameters",
            {"workspace_id": compute_server.workspace_id, "params": {**estimation_case.inputs, field: value}},
        )
    compute_server.resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimation_rejects_missing_source_attribute(compute_server, estimation_case):
    missing = MagicMock(spec=PendingAttribute)
    missing.exists = False
    compute_server.source.attributes["missing"] = missing
    with pytest.raises(ToolError, match="does not exist on the source object"):
        await compute_server.server.call_tool(
            f"{estimation_case.name}_build_parameters",
            {
                "workspace_id": compute_server.workspace_id,
                "params": {**estimation_case.inputs, "point_set_attribute": "missing"},
            },
        )
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimation_rejects_empty_scenarios(compute_server, estimation_case):
    with pytest.raises(ToolError, match="at least one scenario"):
        await compute_server.server.call_tool(
            f"{estimation_case.name}_run", {"workspace_id": compute_server.workspace_id, "scenarios": []}
        )
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimation_reports_compute_errors(compute_server, estimation_case):
    built = await compute_server.server.call_tool(
        f"{estimation_case.name}_build_parameters",
        {"workspace_id": compute_server.workspace_id, "params": estimation_case.inputs},
    )
    compute_server.run.side_effect = RuntimeError("Compute service unavailable")
    with pytest.raises(ToolError, match="Compute service unavailable"):
        await compute_server.server.call_tool(
            f"{estimation_case.name}_run",
            {"workspace_id": compute_server.workspace_id, "scenarios": [built.structured_content]},
        )


@pytest.mark.asyncio
async def test_compute_feedback_forwards_progress():
    context = SimpleNamespace(report_progress=AsyncMock())
    MCPFeedback(context).progress(0.25, "Estimating")
    await asyncio.sleep(0)
    context.report_progress.assert_awaited_once_with(25.0, 100, "Estimating")


ROTATION = {"dip_azimuth": 45.0, "dip": 30.0, "pitch": 10.0}
OTHER_WORKSPACE = "00000000-0000-0000-0000-0000000000ff"


def with_rotation(inputs, key="rotation"):
    search = deepcopy(_search_dict(inputs))
    search["ellipsoid"][key] = ROTATION
    return _with_search(inputs, search)


async def build(compute_server, tool, params):
    result = await compute_server.server.call_tool(
        f"{tool}_build_parameters", {"workspace_id": compute_server.workspace_id, "params": params}
    )
    return result.structured_content


async def run(compute_server, tool, scenarios):
    return await compute_server.server.call_tool(
        f"{tool}_run", {"workspace_id": compute_server.workspace_id, "scenarios": scenarios}
    )


@pytest.mark.asyncio
async def test_estimation_search_rotation_survives_build_and_run(compute_server, estimation_case):
    payload = await build(compute_server, estimation_case.name, with_rotation(estimation_case.inputs))
    assert payload["neighborhood"]["ellipsoid"]["rotation"] == ROTATION
    compute_server.run.return_value = [estimation_result(compute_server)]
    await run(compute_server, estimation_case.name, [payload])
    scenario = compute_server.run.call_args.args[1][0]
    backend = scenario.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert backend["neighborhood"]["ellipsoid"]["rotation"] == ROTATION


@pytest.mark.parametrize("model, fixture_name", [(KrigingBuildParams, "kriging"), (IDWBuildParams, "neighborhood")])
def test_build_models_preserve_rotation_and_reject_typos_directly(
    kriging_build_inputs, neighborhood_build_inputs, model, fixture_name
):
    inputs = kriging_build_inputs if fixture_name == "kriging" else neighborhood_build_inputs
    params = model(**with_rotation(inputs))
    assert params.search.ellipsoid.to_dict()["rotation"] == ROTATION
    base_search = _search_dict(inputs)
    with pytest.raises(ValidationError):
        model(**_with_search(inputs, {**base_search, "min_sample": 3}))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "search_update",
    [{"min_sample": 3}, {"ellipsoid": {"ranges": {"major": 100, "semi_major": 75, "minor": 50}, "rotaton": {}}}],
)
async def test_build_rejects_unknown_search_fields(compute_server, estimation_case, search_update):
    base_search = _search_dict(estimation_case.inputs)
    inputs = _with_search(estimation_case.inputs, {**base_search, **search_update})
    with pytest.raises(InvalidArguments):
        await build(compute_server, estimation_case.name, inputs)
    compute_server.resolve.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path, key",
    [
        ((), "unexpected"),
        ((), "filter"),
        (("neighborhood",), "min_sample"),
        (("neighborhood", "ellipsoid"), "rotaton"),
        (("target",), "filter"),
    ],
)
async def test_estimation_run_rejects_unknown_fields(compute_server, estimation_case, path, key):
    payload = await build(compute_server, estimation_case.name, estimation_case.inputs)
    container = payload
    for part in path:
        container = container[part]
    container[key] = 1
    with pytest.raises(InvalidArguments):
        await run(compute_server, estimation_case.name, [payload])
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("tool", ["idw"])
@pytest.mark.parametrize(
    "override",
    [
        {"neighborhood": {"ellipsoid": {"ranges": {"major": 1, "semi_major": 1, "minor": 1}}, "max_samples": 0}},
        {
            "neighborhood": {
                "ellipsoid": {"ranges": {"major": 1, "semi_major": 1, "minor": 1}},
                "max_samples": 2,
                "min_samples": 3,
            }
        },
    ],
)
async def test_neighborhood_run_rechecks_sample_limits(compute_server, neighborhood_build_inputs, tool, override):
    payload = await build(compute_server, tool, neighborhood_build_inputs)
    with pytest.raises(InvalidArguments, match="min_samples|max_samples"):
        await run(compute_server, tool, [{**payload, **override}])
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_idw_run_rejects_infinite_power(compute_server, neighborhood_build_inputs):
    payload = await build(compute_server, "idw", neighborhood_build_inputs)
    with pytest.raises(InvalidArguments, match="power must be finite"):
        await run(compute_server, "idw", [{**payload, "power": float("inf")}])
    compute_server.run.assert_not_awaited()


def move_reference(reference, *, workspace=None, host=None):
    if workspace is not None:
        reference = reference.replace("00000000-0000-0000-0000-000000000004", workspace)
    if host is not None:
        reference = reference.replace("example.test", host)
    return reference


@pytest.mark.asyncio
@pytest.mark.parametrize("side", ["source", "target"])
@pytest.mark.parametrize("move", [{"workspace": OTHER_WORKSPACE}, {"host": "other.test"}])
async def test_estimation_run_rejects_objects_outside_workspace(compute_server, estimation_case, side, move):
    payload = await build(compute_server, estimation_case.name, estimation_case.inputs)
    payload[side]["object"] = move_reference(payload[side]["object"], **move)
    with pytest.raises(ToolError, match="outside workspace"):
        await run(compute_server, estimation_case.name, [payload])
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_kriging_run_rejects_variogram_outside_workspace(compute_server, kriging_build_inputs):
    payload = await build(compute_server, "kriging", kriging_build_inputs)
    payload["variogram"] = move_reference(payload["variogram"], workspace=OTHER_WORKSPACE)
    with pytest.raises(ToolError, match="outside workspace"):
        await run(compute_server, "kriging", [payload])
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimation_rejects_parallel_writes_to_same_attribute(compute_server, estimation_case):
    payload = await build(compute_server, estimation_case.name, estimation_case.inputs)
    second = deepcopy(payload)
    second["target"]["object"] += "?version=2"
    with pytest.raises(ToolError, match="distinct target attributes"):
        await run(compute_server, estimation_case.name, [payload, second])
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "second_attribute",
    [
        {"operation": "update", "reference": "cell_attributes[?key == 'estimate-key']"},
        {"operation": "update", "reference": "cell_attributes[?'estimate-key' == key]"},
        {"operation": "update", "reference": "cell_attributes[?name=='estimate']"},
        {"operation": "update", "reference": "cell_attributes[?name == 'estimate']"},
        {"operation": "update", "reference": "cell_attributes[0]"},
        {"operation": "create", "name": "estimate"},
    ],
)
async def test_estimation_rejects_equivalent_update_selectors_and_aliases(
    compute_server, estimation_case, second_attribute
):
    attribute = MagicMock(spec=Attribute)
    attribute.name = "estimate"
    attribute.key = "estimate-key"
    attribute.exists = True
    attribute._obj = compute_server.target
    attribute._context = SimpleNamespace(schema_path="cell_attributes")
    compute_server.target.attributes["estimate"] = attribute

    first = await build(compute_server, estimation_case.name, estimation_case.inputs)
    assert first["target"]["attribute"] == {
        "operation": "update",
        "reference": "cell_attributes[?key=='estimate-key']",
    }
    second = deepcopy(first)
    second["target"]["attribute"] = second_attribute

    with pytest.raises(ToolError, match="distinct target attributes"):
        await run(compute_server, estimation_case.name, [first, second])
    compute_server.run.assert_not_awaited()


@pytest.mark.asyncio
async def test_estimation_canonicalizes_selector_whitespace_when_target_unavailable(compute_server, estimation_case):
    compute_server.resolve.side_effect = RuntimeError("Target unavailable")
    first = {
        "source": {
            "object": str(compute_server.source.metadata.url),
            "attribute": "locations.attributes[?key=='grade-key']",
        },
        "target": {
            "object": str(compute_server.target.metadata.url),
            "attribute": {"operation": "update", "reference": "cell_attributes[?key=='estimate-key']"},
        },
        "neighborhood": {
            "ellipsoid": {"ellipsoid_ranges": {"major": 100.0, "semi_major": 75.0, "minor": 50.0}},
            "max_samples": 20,
        },
    }
    if estimation_case.name == "kriging":
        first["variogram"] = str(compute_server.objects["00000000-0000-0000-0000-000000000003"].metadata.url)
    else:
        first["power"] = 2.0
    second = deepcopy(first)
    second["target"]["attribute"] = {"operation": "update", "reference": "cell_attributes[?key == 'estimate-key']"}

    with pytest.raises(ToolError, match="distinct target attributes"):
        await run(compute_server, estimation_case.name, [first, second])
    compute_server.run.assert_not_awaited()


def add_source_attribute(compute_server, name, exists=True):
    attribute = MagicMock(spec=Attribute if exists else PendingAttribute)
    attribute.name = name
    attribute.key = f"{name}-key"
    attribute.exists = exists
    attribute._context = SimpleNamespace(schema_path="locations.attributes")
    compute_server.source.attributes[name] = attribute
