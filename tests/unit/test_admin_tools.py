# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4
from unittest.mock import AsyncMock

import pytest

import evo_mcp.tools.admin_tools as admin_tools
from tests.helpers import FakeMCP


pytestmark = pytest.mark.unit


def _register_admin_tools() -> FakeMCP:
    mcp = FakeMCP()
    admin_tools.register_admin_tools(mcp)
    return mcp


@pytest.mark.asyncio
async def test_create_workspace_maps_response(monkeypatch):
    """Given a created workspace, when the tool runs, then workspace metadata is mapped into the response."""
    monkeypatch.setattr(admin_tools, "ensure_initialized", AsyncMock())

    workspace = SimpleNamespace(
        id=uuid4(),
        display_name="Sandbox",
        description="test workspace",
        created_at=datetime(2026, 1, 5, tzinfo=timezone.utc),
    )
    workspace_client = SimpleNamespace(create_workspace=AsyncMock(return_value=workspace))
    monkeypatch.setattr(admin_tools.evo_context, "workspace_client", workspace_client)

    mcp = _register_admin_tools()
    tool = mcp.tools["create_workspace"]

    result = await tool(name="Sandbox", description="test workspace", labels=["demo"])

    assert result == {
        "id": str(workspace.id),
        "name": "Sandbox",
        "description": "test workspace",
        "created_at": "2026-01-05T00:00:00+00:00",
    }
    workspace_client.create_workspace.assert_awaited_once_with(
        name="Sandbox",
        description="test workspace",
        labels=["demo"],
    )


@pytest.mark.asyncio
async def test_get_workspace_summary_counts_by_schema(monkeypatch):
    """Given workspace objects with mixed schema types, when summarized, then counts are grouped by schema."""
    monkeypatch.setattr(admin_tools, "ensure_initialized", AsyncMock())

    objects = [
        SimpleNamespace(schema_id=SimpleNamespace(sub_classification="pointset")),
        SimpleNamespace(schema_id=SimpleNamespace(sub_classification="pointset")),
        SimpleNamespace(schema_id=SimpleNamespace(sub_classification="line_segments")),
    ]
    object_client = SimpleNamespace(list_all_objects=AsyncMock(return_value=objects))
    get_object_client = AsyncMock(return_value=object_client)
    monkeypatch.setattr(admin_tools.evo_context, "get_object_client", get_object_client)

    mcp = _register_admin_tools()
    tool = mcp.tools["get_workspace_summary"]
    workspace_id = str(uuid4())

    result = await tool(workspace_id=workspace_id)

    assert result == {
        "workspace_id": workspace_id,
        "total_objects": 3,
        "objects_by_schema": {"pointset": 2, "line_segments": 1},
    }
    get_object_client.assert_awaited_once_with(admin_tools.UUID(workspace_id))


@pytest.mark.asyncio
async def test_create_workspace_snapshot_includes_blob_metadata_when_requested(monkeypatch):
    """Given objects with downloadable data, when snapshotting with blobs enabled, then data blob references are included."""
    monkeypatch.setattr(admin_tools, "ensure_initialized", AsyncMock())

    obj_one = SimpleNamespace(
        id=uuid4(),
        name="Samples",
        path="/samples/points.json",
        schema_id=SimpleNamespace(sub_classification="pointset"),
        version_id="v1",
        created_at=datetime(2026, 1, 6, tzinfo=timezone.utc),
    )
    obj_two = SimpleNamespace(
        id=uuid4(),
        name="Broken",
        path="/samples/broken.json",
        schema_id=SimpleNamespace(sub_classification="pointset"),
        version_id="v2",
        created_at=datetime(2026, 1, 7, tzinfo=timezone.utc),
    )
    downloaded = SimpleNamespace(as_dict=lambda: {"channels": [{"data": "blob-1"}]})
    object_client = SimpleNamespace(
        list_all_objects=AsyncMock(return_value=[obj_one, obj_two]),
        download_object_by_id=AsyncMock(side_effect=[downloaded, RuntimeError("download failed")]),
    )
    workspace_client = SimpleNamespace(
        get_workspace=AsyncMock(return_value=SimpleNamespace(display_name="Sandbox", description="desc"))
    )

    monkeypatch.setattr(admin_tools.evo_context, "workspace_client", workspace_client)
    monkeypatch.setattr(admin_tools.evo_context, "get_object_client", AsyncMock(return_value=object_client))
    monkeypatch.setattr(admin_tools, "extract_data_references", lambda payload: ["blob-1"])

    mcp = _register_admin_tools()
    tool = mcp.tools["create_workspace_snapshot"]
    workspace_id = str(uuid4())

    result = await tool(
        workspace_id=workspace_id,
        snapshot_name="snapshot-demo",
        include_data_blobs=True,
    )

    assert result["summary"]["snapshot_name"] == "snapshot-demo"
    assert result["summary"]["total_objects"] == 2
    assert result["snapshot"]["workspace_name"] == "Sandbox"
    assert result["snapshot"]["objects"][0]["data_blobs"] == ["blob-1"]
    assert result["snapshot"]["objects"][1]["data_blobs"] == []


@pytest.mark.asyncio
async def test_workspace_copy_object_copies_blob_data_and_clears_uuid(monkeypatch):
    """Given a source object with blob references, when copied, then blobs are copied and the created object has no uuid."""
    monkeypatch.setattr(admin_tools, "ensure_initialized", AsyncMock())

    metadata = SimpleNamespace(path="/samples/points.json")
    object_dict = {"uuid": "original-id", "channels": [{"data": "blob-1"}]}
    source_object = SimpleNamespace(metadata=metadata, as_dict=lambda: object_dict)
    new_metadata = SimpleNamespace(id=uuid4(), name="Points", path="/samples/points.json", version_id="v9")
    source_client = SimpleNamespace(download_object_by_id=AsyncMock(return_value=source_object))
    target_client = SimpleNamespace(create_geoscience_object=AsyncMock(return_value=new_metadata))
    get_object_client = AsyncMock(side_effect=[source_client, target_client])
    copy_object_data = AsyncMock()

    monkeypatch.setattr(admin_tools.evo_context, "get_object_client", get_object_client)
    monkeypatch.setattr(admin_tools.evo_context, "connector", SimpleNamespace())
    monkeypatch.setattr(admin_tools, "extract_data_references", lambda payload: ["blob-1"])
    monkeypatch.setattr(admin_tools, "copy_object_data", copy_object_data)

    mcp = _register_admin_tools()
    tool = mcp.tools["workspace_copy_object"]
    source_workspace_id = str(uuid4())
    target_workspace_id = str(uuid4())
    object_id = str(uuid4())

    result = await tool(
        source_workspace_id=source_workspace_id,
        target_workspace_id=target_workspace_id,
        object_id=object_id,
        version="v3",
    )

    copy_object_data.assert_awaited_once()
    target_client.create_geoscience_object.assert_awaited_once_with(
        "/samples/points.json",
        {"uuid": None, "channels": [{"data": "blob-1"}]},
    )
    assert result["data_blobs_copied"] == 1
    assert result["version_id"] == "v9"


@pytest.mark.asyncio
async def test_workspace_duplicate_workspace_filters_objects_and_tracks_failures(monkeypatch):
    """Given filtered source objects, when duplicating, then only matching objects are copied and failures are counted."""
    monkeypatch.setattr(admin_tools, "ensure_initialized", AsyncMock())

    obj_keep_one = SimpleNamespace(
        id=uuid4(),
        name="Points A",
        path="/samples/a.json",
        schema_id=SimpleNamespace(sub_classification="pointset"),
        version_id="v1",
    )
    obj_keep_two = SimpleNamespace(
        id=uuid4(),
        name="Points B",
        path="/samples/b.json",
        schema_id=SimpleNamespace(sub_classification="pointset"),
        version_id="v2",
    )
    obj_skip = SimpleNamespace(
        id=uuid4(),
        name="Lines",
        path="/lines/c.json",
        schema_id=SimpleNamespace(sub_classification="line_segments"),
        version_id="v3",
    )
    source_objects = [obj_keep_one, obj_keep_two, obj_skip]

    target_workspace = SimpleNamespace(id=uuid4(), display_name="Cloned")
    workspace_client = SimpleNamespace(create_workspace=AsyncMock(return_value=target_workspace))

    source_object_one = SimpleNamespace(
        metadata=SimpleNamespace(path="/samples/a.json"),
        as_dict=lambda: {"uuid": "one", "channels": [{"data": "blob-1"}]},
    )
    source_client = SimpleNamespace(
        list_all_objects=AsyncMock(return_value=source_objects),
        download_object_by_id=AsyncMock(side_effect=[source_object_one, RuntimeError("copy failed")]),
    )
    target_client = SimpleNamespace(create_geoscience_object=AsyncMock(return_value=SimpleNamespace()))
    get_object_client = AsyncMock(side_effect=[source_client, target_client])
    copy_object_data = AsyncMock()

    monkeypatch.setattr(admin_tools.evo_context, "workspace_client", workspace_client)
    monkeypatch.setattr(admin_tools.evo_context, "get_object_client", get_object_client)
    monkeypatch.setattr(admin_tools.evo_context, "connector", SimpleNamespace())
    monkeypatch.setattr(admin_tools, "extract_data_references", lambda payload: ["blob-1"])
    monkeypatch.setattr(admin_tools, "copy_object_data", copy_object_data)

    mcp = _register_admin_tools()
    tool = mcp.tools["workspace_duplicate_workspace"]
    source_workspace_id = str(uuid4())

    result = await tool(
        source_workspace_id=source_workspace_id,
        target_name="Cloned",
        target_description="copy",
        schema_filter=["pointset"],
        name_filter=["Points A", "Points B"],
    )

    workspace_client.create_workspace.assert_awaited_once_with(
        name="Cloned",
        description="copy",
    )
    copy_object_data.assert_awaited_once()
    target_client.create_geoscience_object.assert_awaited_once_with(
        "/samples/a.json",
        {"uuid": None, "channels": [{"data": "blob-1"}]},
    )
    assert result == {
        "target_workspace_id": str(target_workspace.id),
        "target_workspace_name": "Cloned",
        "objects_copied": 1,
        "objects_failed": 1,
        "data_blobs_copied": 1,
    }
