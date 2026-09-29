# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

import hashlib
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError

import evo_mcp.context as context_module
import evo_mcp.file_transfer as file_transfer
from evo_mcp.session.registry import ObjectRegistry
from evo_mcp.staging.objects import point_set
from evo_mcp.staging.service import StagingService
from evo_mcp.tools import file_tools, filesystem_tools, object_build_tools, remote_file_tools

WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
COMMON = {
    "workspace_id": WORKSPACE_ID,
    "object_path": "/test.json",
    "object_name": "Test",
    "description": "Test",
}
XYZ = {"x_column": "X", "y_column": "Y", "z_column": "Z"}
CSVS = {
    "points.csv": b"\xef\xbb\xbfX,Y,Z,NAME\r\n1,2,3,caf\xc3\xa9\r\n4,5,6,other\r\n",
    "segments.csv": b"START,END\r\n0,1\r\n",
    "collar.csv": b"ID,X,Y,Z\r\nHOLE1,1,2,3\r\n",
    "survey.csv": b"ID,DEPTH,AZ,DIP\r\nHOLE1,0,0,-90\r\nHOLE1,10,0,-90\r\n",
    "intervals.csv": b"ID,FROM,TO,X,Y,Z,GRADE\r\nHOLE1,0,10,1,2,3,0.5\r\n",
}
BUILDERS = [
    ("build_and_create_pointset", {**XYZ, "csv_file": "points.csv"}),
    (
        "build_and_create_line_segments",
        {
            **XYZ,
            "vertices_file": "points.csv",
            "segments_file": "segments.csv",
            "start_index_column": "START",
            "end_index_column": "END",
        },
    ),
    (
        "build_and_create_downhole_collection",
        {
            **XYZ,
            "collar_file": "collar.csv",
            "survey_file": "survey.csv",
            "collar_id_column": "ID",
            "survey_id_column": "ID",
            "depth_column": "DEPTH",
            "azimuth_column": "AZ",
            "dip_column": "DIP",
            "interval_files": [
                {"file": "intervals.csv", "name": "assay", "id_column": "ID", "from_column": "FROM", "to_column": "TO"}
            ],
        },
    ),
    (
        "build_and_create_downhole_intervals",
        {
            "csv_file": "intervals.csv",
            "hole_id_column": "ID",
            "from_column": "FROM",
            "to_column": "TO",
            **{
                f"{position}_{axis.lower()}_column": axis
                for position in ("start", "end", "mid")
                for axis in ("X", "Y", "Z")
            },
        },
    ),
]


def _file_arguments(arguments, sources):
    result = deepcopy(arguments)
    for key in ("csv_file", "vertices_file", "segments_file", "collar_file", "survey_file"):
        if key in result:
            result[key] = sources[result[key]]
    for interval in result.get("interval_files", []):
        interval["file"] = sources[interval["file"]]
    return result


@pytest.fixture
def hosted(tmp_path, monkeypatch):
    store = file_transfer.FileTransfers(tmp_path)
    staging = StagingService()
    context = SimpleNamespace(
        file_transfers=store,
        get_file_client=AsyncMock(),
        connector=SimpleNamespace(transport=object()),
        object_staging=staging,
        object_registry=ObjectRegistry(staging),
    )
    get_context = AsyncMock(return_value=context)
    for module in (context_module, remote_file_tools, object_build_tools, point_set):
        monkeypatch.setattr(module, "get_evo_context", get_context)
    monkeypatch.setattr(file_transfer, "REMOTE_FILE_TRANSFER", True)
    monkeypatch.setattr(filesystem_tools, "REMOTE_FILE_TRANSFER", True)
    mcp = FastMCP("hosted-test")
    remote_file_tools.register_remote_input_tools(mcp, "https://example.com/instance/evo-mcp-hosting")
    remote_file_tools.register_remote_file_tools(mcp)
    object_build_tools.register_object_builder_tools(mcp)
    yield mcp, context
    store.cleanup()


async def _receive(mcp, name, content):
    prepared = (
        await mcp.call_tool(
            "prepare_file_upload",
            {"file_name": name, "size_bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()},
        )
    ).structured_content
    assert prepared["url"] == "https://example.com/instance/evo-mcp-hosting/file-transfer"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=mcp.http_app()), base_url="https://test") as client:
        response = await client.put("/file-transfer", headers=prepared["headers"], content=content)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "received"
    return prepared["file_ref"]


@pytest.mark.asyncio
async def test_hosted_upload_streams_original_bytes_through_sdk(hosted):
    mcp, context = hosted
    content = b"\x89PNG\r\n\x1a\n\x00\xffbinary"
    reference = await _receive(mcp, "image.png", content)
    uploaded = []

    async def upload_from_path(path, transport):
        uploaded.append(Path(path).read_bytes())
        assert transport is context.connector.transport

    upload = SimpleNamespace(
        file_id=UUID(WORKSPACE_ID), version_id="version", upload_from_path=AsyncMock(side_effect=upload_from_path)
    )
    client = context.get_file_client.return_value
    client.prepare_upload_by_path.return_value = upload
    result = (
        await mcp.call_tool(
            "upload_file", {"workspace_id": WORKSPACE_ID, "file_ref": reference, "target_path": "imports/"}
        )
    ).structured_content
    assert uploaded == [content]
    assert result == {
        "status": "uploaded",
        "file_id": WORKSPACE_ID,
        "path": "/imports/image.png",
        "version_id": "version",
        "size_bytes": len(content),
    }
    client.prepare_upload_by_path.assert_awaited_once_with("/imports/image.png")


@pytest.mark.asyncio
async def test_hosted_upload_failure_is_not_reported_as_success(hosted):
    mcp, context = hosted
    reference = await _receive(mcp, "points.csv", CSVS["points.csv"])
    context.get_file_client.return_value.prepare_upload_by_path.side_effect = RuntimeError("Upload unavailable")
    with pytest.raises(ToolError, match="Upload unavailable"):
        await mcp.call_tool("upload_file", {"workspace_id": WORKSPACE_ID, "file_ref": reference})


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup", ["expire", "session"])
async def test_workspace_upload_keeps_input_until_sdk_finishes(hosted, cleanup):
    mcp, context = hosted
    content = CSVS["points.csv"]
    reference = await _receive(mcp, "points.csv", content)
    store = context.file_transfers
    path = store.resolve(reference)

    async def upload_from_path(source, transport):
        if cleanup == "expire":
            store._entries[reference].expires_at = 0
            store._prune_expired()
        else:
            store.cleanup()
        assert Path(source).read_bytes() == content

    context.get_file_client.return_value.prepare_upload_by_path.return_value = SimpleNamespace(
        file_id=UUID(WORKSPACE_ID),
        version_id="version",
        upload_from_path=AsyncMock(side_effect=upload_from_path),
    )
    result = (
        await mcp.call_tool("upload_file", {"workspace_id": WORKSPACE_ID, "file_ref": reference})
    ).structured_content
    assert result["status"] == "uploaded"
    assert result["size_bytes"] == len(content)
    if cleanup == "session":
        assert not path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["", "historical"])
async def test_hosted_download_returns_transfer_metadata_not_bytes(hosted, version):
    mcp, context = hosted
    client = context.get_file_client.return_value
    client.prepare_download_by_path.return_value = SimpleNamespace(
        metadata=SimpleNamespace(name="data.csv", version_id=version or "latest", size=123),
        get_download_url=AsyncMock(return_value="https://storage.example/download"),
    )
    result = (
        await mcp.call_tool(
            "download_file", {"workspace_id": WORKSPACE_ID, "file_path": "data.csv", "version": version}
        )
    ).structured_content
    assert result == {
        "status": "download_ready",
        "file_path": "/data.csv",
        "file_name": "data.csv",
        "version_id": version or "latest",
        "size_bytes": 123,
        "url": "https://storage.example/download",
        "method": "GET",
        "headers": {},
    }
    client.prepare_download_by_path.assert_awaited_once_with("/data.csv", version_id=version or None)


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", BUILDERS)
async def test_csv_builders_preserve_local_results_for_uploaded_input(hosted, tmp_path, monkeypatch, tool, arguments):
    mcp, context = hosted
    local_sources = {}
    remote_sources = {}
    for name, content in CSVS.items():
        path = tmp_path / name
        path.write_bytes(content)
        local_sources[name] = str(path)
        remote_sources[name] = await _receive(mcp, name, content)

    remote_result = (
        await mcp.call_tool(tool, {**COMMON, **_file_arguments(arguments, remote_sources)})
    ).structured_content
    monkeypatch.setattr(file_transfer, "REMOTE_FILE_TRANSFER", False)
    local_result = (
        await mcp.call_tool(tool, {**COMMON, **_file_arguments(arguments, local_sources)})
    ).structured_content
    assert local_result["status"] == "validation_passed"
    assert remote_result == local_result
    context.get_file_client.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "builder_index,missing_key,label",
    [
        (0, "csv_file", "CSV"),
        (1, "vertices_file", "Vertices"),
        (1, "segments_file", "Segments"),
        (2, "collar_file", "Collar"),
        (2, "survey_file", "Survey"),
        (3, "csv_file", "CSV"),
    ],
)
async def test_local_csv_missing_file_responses(tmp_path, monkeypatch, builder_index, missing_key, label):
    monkeypatch.setattr(file_transfer, "REMOTE_FILE_TRANSFER", False)
    mcp = FastMCP("local-test")
    object_build_tools.register_object_builder_tools(mcp)
    sources = {}
    for name, content in CSVS.items():
        path = tmp_path / name
        path.write_bytes(content)
        sources[name] = str(path)
    tool, arguments = BUILDERS[builder_index]
    arguments = _file_arguments(arguments, sources)
    arguments[missing_key] = str(tmp_path / "missing.csv")
    result = (await mcp.call_tool(tool, {**COMMON, **arguments})).structured_content
    assert result == {"status": "error", "error": f"{label} file not found: {arguments[missing_key]}"}


@pytest.mark.asyncio
async def test_local_interval_missing_file_accumulates_original_error(tmp_path, monkeypatch):
    monkeypatch.setattr(file_transfer, "REMOTE_FILE_TRANSFER", False)
    mcp = FastMCP("local-test")
    object_build_tools.register_object_builder_tools(mcp)
    sources = {}
    for name, content in CSVS.items():
        path = tmp_path / name
        path.write_bytes(content)
        sources[name] = str(path)
    tool, arguments = BUILDERS[2]
    arguments = _file_arguments(arguments, sources)
    missing = tmp_path / "missing.csv"
    arguments["interval_files"][0]["file"] = str(missing)
    result = (await mcp.call_tool(tool, {**COMMON, **arguments})).structured_content
    assert result["status"] == "validation_failed"
    assert result["validation"]["errors"] == [f"Interval file not found: {missing}"]


@pytest.mark.asyncio
async def test_uploaded_csv_preview_and_staged_pointset(hosted):
    mcp, context = hosted
    reference = await _receive(mcp, "points.csv", CSVS["points.csv"])
    preview = (await mcp.call_tool("preview_csv_file", {"file_path": reference})).structured_content
    assert preview["file_path"] == reference
    assert preview["total_rows"] == 2
    assert preview["sample_data"][0]["NAME"] == "caf\u00e9"
    result = await point_set._create(point_set.PointSetCreateParams(object_name="Points", csv_file=reference, **XYZ))
    assert result["message"] == "Point set created."
    assert result["summary"]["point_count"] == 2
    context.get_file_client.assert_not_awaited()


@pytest.mark.asyncio
async def test_hosted_tools_reject_server_paths(hosted):
    mcp, _ = hosted
    with pytest.raises(ToolError):
        await mcp.call_tool("preview_csv_file", {"file_path": "/etc/passwd"})
    result = (
        await mcp.call_tool("build_and_create_pointset", {**COMMON, **XYZ, "csv_file": "/etc/passwd"})
    ).structured_content
    assert result["status"] == "error"
    assert "Failed to read CSV file" in result["error"]


@pytest.mark.asyncio
async def test_catalogs_keep_local_schemas_and_expose_hosted_handoff(hosted):
    hosted_mcp, _ = hosted
    local_mcp = FastMCP("local")
    file_tools.register_file_tools(local_mcp)
    filesystem_tools.register_filesystem_tools(local_mcp)
    local_tools = {tool.name: tool for tool in await local_mcp.list_tools()}
    hosted_tools = {tool.name: tool for tool in await hosted_mcp.list_tools()}
    assert "local_file_path" in local_tools["upload_file"].parameters["properties"]
    assert "local_filename" in local_tools["download_file"].parameters["properties"]
    assert "file_ref" in hosted_tools["upload_file"].parameters["properties"]
    assert {"list_files", "list_file_versions", "preview_csv_file"} <= local_tools.keys() & hosted_tools.keys()
    assert {"prepare_file_upload", "upload_file", "download_file"} <= hosted_tools.keys()
    assert not {"configure_local_data_directory", "list_local_data_files"} & hosted_tools.keys()
