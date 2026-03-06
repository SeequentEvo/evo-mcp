from __future__ import annotations

import pytest

from evo_mcp.tools.object_build_tools import register_object_builder_tools
from tests.helpers import FakeMCP


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_build_and_create_pointset_dry_run_passes(tmp_path):
    """Given valid pointset CSV input, when dry-run is enabled, then validation passes with a preview."""
    csv_path = tmp_path / "points.csv"
    csv_path.write_text("X,Y,Z,grade\n1,2,3,0.1\n4,5,6,0.2\n", encoding="utf-8")

    mcp = FakeMCP()
    register_object_builder_tools(mcp)

    tool = mcp.tools["build_and_create_pointset"]
    result = await tool(
        workspace_id="00000000-0000-0000-0000-000000000000",
        object_path="/samples/points.json",
        object_name="Points",
        description="test",
        csv_file=str(csv_path),
        x_column="X",
        y_column="Y",
        z_column="Z",
        dry_run=True,
    )

    assert result["status"] == "validation_passed"
    assert result["validation"]["data_summary"]["valid_points"] == 2
    assert "object_preview" in result


@pytest.mark.asyncio
async def test_build_and_create_pointset_missing_required_column_fails(tmp_path):
    """Given missing coordinate columns, when validating pointset CSV, then validation fails."""
    csv_path = tmp_path / "points_missing.csv"
    csv_path.write_text("X,Y,grade\n1,2,0.1\n", encoding="utf-8")

    mcp = FakeMCP()
    register_object_builder_tools(mcp)

    tool = mcp.tools["build_and_create_pointset"]
    result = await tool(
        workspace_id="00000000-0000-0000-0000-000000000000",
        object_path="/samples/points.json",
        object_name="Points",
        description="test",
        csv_file=str(csv_path),
        x_column="X",
        y_column="Y",
        z_column="Z",
        dry_run=True,
    )

    assert result["status"] == "validation_failed"
    assert "Missing required columns" in result["validation"]["errors"][0]
