# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os

import pytest

from evo_mcp.tools.filesystem_tools import register_filesystem_tools
from tests.helpers import FakeMCP


pytestmark = pytest.mark.unit


@pytest.mark.asyncio
async def test_configure_local_data_directory_invalid_path_returns_error(tmp_path):
    """Given a missing directory, when configured, then status is invalid."""
    mcp = FakeMCP()
    register_filesystem_tools(mcp)

    tool = mcp.tools["configure_local_data_directory"]
    result = await tool(directory_path=str(tmp_path / "missing"))

    assert result["status"] == "invalid"
    assert "does not exist" in result["error"]


@pytest.mark.asyncio
async def test_list_local_data_files_recursive_finds_csv(tmp_path, monkeypatch):
    """Given nested CSV files, when listing recursively, then both files are returned."""
    (tmp_path / "a.csv").write_text("x,y,z\n1,2,3\n", encoding="utf-8")
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "b.csv").write_text("x,y,z\n4,5,6\n", encoding="utf-8")

    monkeypatch.setenv("EVO_LOCAL_DATA_DIR", str(tmp_path))

    mcp = FakeMCP()
    register_filesystem_tools(mcp)

    tool = mcp.tools["list_local_data_files"]
    result = await tool(file_pattern="*.csv", recursive=True)

    assert result["file_count"] == 2
    names = sorted(file_info["name"] for file_info in result["files"])
    assert names == ["a.csv", "b.csv"]


@pytest.mark.asyncio
async def test_preview_csv_file_returns_schema_and_sample(tmp_path, monkeypatch):
    """Given a valid CSV, when previewed, then schema metadata and sample rows are returned."""
    csv_path = tmp_path / "points.csv"
    csv_path.write_text("X,Y,Z,grade\n1,2,3,0.1\n4,5,6,0.3\n", encoding="utf-8")

    monkeypatch.setenv("EVO_LOCAL_DATA_DIR", str(tmp_path))

    mcp = FakeMCP()
    register_filesystem_tools(mcp)

    tool = mcp.tools["preview_csv_file"]
    result = await tool(file_path="points.csv", max_rows=1)

    assert result["total_rows"] == 2
    assert result["total_columns"] == 4
    assert len(result["sample_data"]) == 1
    assert any(col["name"] == "X" for col in result["columns"])


@pytest.mark.asyncio
async def test_preview_csv_file_missing_returns_file_missing(tmp_path, monkeypatch):
    """Given a missing CSV, when previewed, then the response status is file_missing."""
    monkeypatch.setenv("EVO_LOCAL_DATA_DIR", str(tmp_path))

    mcp = FakeMCP()
    register_filesystem_tools(mcp)

    tool = mcp.tools["preview_csv_file"]
    result = await tool(file_path="missing.csv")

    assert result["status"] == "file_missing"
    assert "File not found" in result["error"]
