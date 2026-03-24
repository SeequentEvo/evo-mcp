# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from evo_mcp.tools.object_build_tools import register_object_builder_tools
from tests.helpers import FakeMCP


pytestmark = pytest.mark.unit


def _register_builder_tools() -> FakeMCP:
    mcp = FakeMCP()
    register_object_builder_tools(mcp)
    return mcp


@pytest.mark.asyncio
async def test_build_and_create_pointset_dry_run_passes(tmp_path):
    """Given valid pointset CSV input, when dry-run is enabled, then validation passes with a preview."""
    csv_path = tmp_path / "points.csv"
    csv_path.write_text("X,Y,Z,grade\n1,2,3,0.1\n4,5,6,0.2\n", encoding="utf-8")

    mcp = _register_builder_tools()

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

    mcp = _register_builder_tools()

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


@pytest.mark.asyncio
async def test_build_and_create_line_segments_dry_run_passes(tmp_path):
    """Given valid line inputs, when dry-run is enabled, then validation passes with counts."""
    vertices_path = tmp_path / "vertices.csv"
    vertices_path.write_text("X,Y,Z,label\n0,0,0,a\n1,1,1,b\n2,2,2,c\n", encoding="utf-8")

    segments_path = tmp_path / "segments.csv"
    segments_path.write_text("start_idx,end_idx,kind\n0,1,ore\n1,2,waste\n", encoding="utf-8")

    mcp = _register_builder_tools()

    tool = mcp.tools["build_and_create_line_segments"]
    result = await tool(
        workspace_id="00000000-0000-0000-0000-000000000000",
        object_path="/lines/segments.json",
        object_name="Segments",
        description="test",
        vertices_file=str(vertices_path),
        segments_file=str(segments_path),
        x_column="X",
        y_column="Y",
        z_column="Z",
        start_index_column="start_idx",
        end_index_column="end_idx",
        dry_run=True,
    )

    assert result["status"] == "validation_passed"
    assert result["object_preview"]["vertices"] == 3
    assert result["object_preview"]["segments"] == 2


@pytest.mark.asyncio
async def test_build_and_create_line_segments_invalid_indices_fail(tmp_path):
    """Given out-of-range segment indices, when validating, then the tool reports invalid indices."""
    vertices_path = tmp_path / "vertices.csv"
    vertices_path.write_text("X,Y,Z\n0,0,0\n1,1,1\n", encoding="utf-8")

    segments_path = tmp_path / "segments.csv"
    segments_path.write_text("start_idx,end_idx\n0,3\n", encoding="utf-8")

    mcp = _register_builder_tools()

    tool = mcp.tools["build_and_create_line_segments"]
    result = await tool(
        workspace_id="00000000-0000-0000-0000-000000000000",
        object_path="/lines/segments.json",
        object_name="Segments",
        description="test",
        vertices_file=str(vertices_path),
        segments_file=str(segments_path),
        x_column="X",
        y_column="Y",
        z_column="Z",
        start_index_column="start_idx",
        end_index_column="end_idx",
        dry_run=True,
    )

    assert result["status"] == "validation_failed"
    assert "Segment indices exceed vertex count" in result["validation"]["errors"][0]


@pytest.mark.asyncio
async def test_build_and_create_downhole_collection_dry_run_passes(tmp_path):
    """Given valid collar, survey, and interval inputs, when dry-run is enabled, then validation passes."""
    collar_path = tmp_path / "collar.csv"
    collar_path.write_text(
        "hole_id,X,Y,Z,max_depth\nDH001,100,200,300,120\nDH002,110,210,310,150\n",
        encoding="utf-8",
    )

    survey_path = tmp_path / "survey.csv"
    survey_path.write_text(
        "hole_id,depth,azimuth,dip\nDH001,0,0,-90\nDH001,120,0,-85\nDH002,0,90,-90\nDH002,150,90,-80\n",
        encoding="utf-8",
    )

    interval_path = tmp_path / "assay.csv"
    interval_path.write_text(
        "hole_id,from_depth,to_depth,grade\nDH001,0,10,0.1\nDH002,20,40,0.4\n",
        encoding="utf-8",
    )

    mcp = _register_builder_tools()

    tool = mcp.tools["build_and_create_downhole_collection"]
    result = await tool(
        workspace_id="00000000-0000-0000-0000-000000000000",
        object_path="/drillholes/collection.json",
        object_name="Collection",
        description="test",
        collar_file=str(collar_path),
        survey_file=str(survey_path),
        collar_id_column="hole_id",
        survey_id_column="hole_id",
        x_column="X",
        y_column="Y",
        z_column="Z",
        depth_column="depth",
        azimuth_column="azimuth",
        dip_column="dip",
        max_depth_column="max_depth",
        interval_files=[
            {
                "file": str(interval_path),
                "name": "assay",
                "id_column": "hole_id",
                "from_column": "from_depth",
                "to_column": "to_depth",
            }
        ],
        dry_run=True,
    )

    assert result["status"] == "validation_passed"
    assert result["validation"]["data_summary"]["unique_holes"] == 2
    assert result["object_preview"]["collections"] == ["assay"]


@pytest.mark.asyncio
async def test_build_and_create_downhole_collection_missing_interval_column_fails(tmp_path):
    """Given an invalid interval config, when validating, then the missing interval columns are reported."""
    collar_path = tmp_path / "collar.csv"
    collar_path.write_text("hole_id,X,Y,Z\nDH001,100,200,300\n", encoding="utf-8")

    survey_path = tmp_path / "survey.csv"
    survey_path.write_text("hole_id,depth,azimuth,dip\nDH001,0,0,-90\n", encoding="utf-8")

    interval_path = tmp_path / "assay.csv"
    interval_path.write_text("hole_id,from_depth,grade\nDH001,0,0.1\n", encoding="utf-8")

    mcp = _register_builder_tools()

    tool = mcp.tools["build_and_create_downhole_collection"]
    result = await tool(
        workspace_id="00000000-0000-0000-0000-000000000000",
        object_path="/drillholes/collection.json",
        object_name="Collection",
        description="test",
        collar_file=str(collar_path),
        survey_file=str(survey_path),
        collar_id_column="hole_id",
        survey_id_column="hole_id",
        x_column="X",
        y_column="Y",
        z_column="Z",
        depth_column="depth",
        azimuth_column="azimuth",
        dip_column="dip",
        interval_files=[
            {
                "file": str(interval_path),
                "name": "assay",
                "id_column": "hole_id",
                "from_column": "from_depth",
                "to_column": "to_depth",
            }
        ],
        dry_run=True,
    )

    assert result["status"] == "validation_failed"
    assert "Interval 'assay' missing columns" in result["validation"]["errors"][0]


@pytest.mark.asyncio
async def test_build_and_create_downhole_intervals_dry_run_passes(tmp_path):
    """Given valid interval coordinates, when dry-run is enabled, then validation passes with preview details."""
    csv_path = tmp_path / "intervals.csv"
    csv_path.write_text(
        "hole_id,from_depth,to_depth,start_x,start_y,start_z,end_x,end_y,end_z,mid_x,mid_y,mid_z,grade\n"
        "DH001,0,10,0,0,0,10,0,-10,5,0,-5,0.1\n"
        "DH001,10,20,10,0,-10,20,0,-20,15,0,-15,0.2\n",
        encoding="utf-8",
    )

    mcp = _register_builder_tools()

    tool = mcp.tools["build_and_create_downhole_intervals"]
    result = await tool(
        workspace_id="00000000-0000-0000-0000-000000000000",
        object_path="/intervals/assay.json",
        object_name="Assay",
        description="test",
        csv_file=str(csv_path),
        hole_id_column="hole_id",
        from_column="from_depth",
        to_column="to_depth",
        start_x_column="start_x",
        start_y_column="start_y",
        start_z_column="start_z",
        end_x_column="end_x",
        end_y_column="end_y",
        end_z_column="end_z",
        mid_x_column="mid_x",
        mid_y_column="mid_y",
        mid_z_column="mid_z",
        dry_run=True,
    )

    assert result["status"] == "validation_passed"
    assert result["validation"]["data_summary"]["valid_intervals"] == 2
    assert result["object_preview"]["holes"] == 1


@pytest.mark.asyncio
async def test_build_and_create_downhole_intervals_missing_required_column_fails(tmp_path):
    """Given a missing midpoint column, when validating, then the tool reports the required column error."""
    csv_path = tmp_path / "intervals_missing.csv"
    csv_path.write_text(
        "hole_id,from_depth,to_depth,start_x,start_y,start_z,end_x,end_y,end_z,mid_x,mid_y,grade\n"
        "DH001,0,10,0,0,0,10,0,-10,5,0,0.1\n",
        encoding="utf-8",
    )

    mcp = _register_builder_tools()

    tool = mcp.tools["build_and_create_downhole_intervals"]
    result = await tool(
        workspace_id="00000000-0000-0000-0000-000000000000",
        object_path="/intervals/assay.json",
        object_name="Assay",
        description="test",
        csv_file=str(csv_path),
        hole_id_column="hole_id",
        from_column="from_depth",
        to_column="to_depth",
        start_x_column="start_x",
        start_y_column="start_y",
        start_z_column="start_z",
        end_x_column="end_x",
        end_y_column="end_y",
        end_z_column="end_z",
        mid_x_column="mid_x",
        mid_y_column="mid_y",
        mid_z_column="mid_z",
        dry_run=True,
    )

    assert result["status"] == "validation_failed"
    assert "Missing required columns" in result["validation"]["errors"][0]
