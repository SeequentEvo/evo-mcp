# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from typing import Any

import pytest
from pydantic import ValidationError

from evo_mcp.tools.compute_tools import KrigingBuildParams


@pytest.fixture
def kriging_build_inputs() -> dict[str, Any]:
    return {
        "target_object_id": "00000000-0000-0000-0000-000000000001",
        "target_attribute": "estimate",
        "point_set_object_id": "00000000-0000-0000-0000-000000000002",
        "point_set_attribute": "grade",
        "variogram_object_id": "00000000-0000-0000-0000-000000000003",
        "search": {
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


def test_kriging_build_schema_uses_canonical_discretization():
    properties = KrigingBuildParams.model_json_schema()["properties"]
    assert "block_discretization" in properties
    assert "block_discretisation" not in properties


@pytest.mark.parametrize("include_canonical", [False, True])
def test_kriging_build_rejects_legacy_discretisation(kriging_build_inputs, include_canonical):
    legacy_inputs = {**kriging_build_inputs, "block_discretisation": {"nx": 2, "ny": 3, "nz": 4}}
    if include_canonical:
        legacy_inputs["block_discretization"] = {"nx": 2, "ny": 3, "nz": 4}

    with pytest.raises(ValidationError, match="block_discretisation"):
        KrigingBuildParams(**legacy_inputs)
