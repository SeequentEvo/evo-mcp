# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pyarrow as pa
import pyarrow.parquet as pq

from evo_mcp.tools.admin_tools import _inspect_parquet_bytes, _resolve_object_side, register_admin_tools


class _FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


def _parquet_bytes() -> bytes:
    table = pa.table(
        {
            "sample_id": pa.array([1, 2, 3], type=pa.int32()),
            "label": pa.array(["a", "b", "c"], type=pa.string()),
        }
    )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, version="2.6")
    return sink.getvalue().to_pybytes()


class InspectParquetBytesTests(unittest.TestCase):
    def test_extracts_core_parquet_metadata(self) -> None:
        result = _inspect_parquet_bytes("blob-a", _parquet_bytes())

        self.assertEqual("blob-a", result["blob_name"])
        self.assertEqual(3, result["num_rows"])
        self.assertEqual(2, result["num_columns"])
        self.assertEqual(1, result["num_row_groups"])
        self.assertTrue(result["parquet_format_version"])
        self.assertIn("sample_id", result["arrow_schema"])
        self.assertEqual(
            [
                {"name": "sample_id", "type": "int32", "nullable": True},
                {"name": "label", "type": "string", "nullable": True},
            ],
            result["fields"],
        )


class CompareEvoObjectsDetailedTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_object_side_uses_downloaded_object_payload_and_urls(self) -> None:
        fake_workspace = SimpleNamespace(
            id="workspace-1",
            display_name="Workspace One",
            get_environment=lambda: "workspace-env",
        )
        fake_downloaded = SimpleNamespace(
            metadata=SimpleNamespace(
                id="object-1",
                name="Object One",
                path="/Object One.json",
                version_id="v1",
                schema_id=SimpleNamespace(sub_classification="pointsets"),
                created_at=None,
                modified_at=None,
            ),
            as_dict=lambda: {
                "schema": "/objects/pointsets/1.0.0/pointsets.schema.json",
                "crs": "EPSG:2193",
                "properties": {"units": "m"},
            },
            _urls_by_name={
                "blob-a": "https://example.invalid/a",
                "blob-b": "https://example.invalid/b",
            },
        )
        fake_object_client = SimpleNamespace(
            download_object_by_id=AsyncMock(return_value=fake_downloaded),
        )
        fake_connector = SimpleNamespace(_transport=object(), _authorizer=object())
        fake_evo_context = SimpleNamespace(connector=fake_connector)

        async def fake_inspect_data_link(link, connector, *, hub_url="", session=None):
            return {
                "blob_name": link["name"],
                "download_url": link["download_url"],
                "num_rows": 3,
            }

        with (
            patch(
                "evo_mcp.tools.admin_tools._resolve_instance",
                AsyncMock(
                    return_value={"id": "instance-1", "name": "Instance One", "hub_url": "https://hub.example.invalid"}
                ),
            ),
            patch("evo_mcp.tools.admin_tools._resolve_workspace", AsyncMock(return_value=fake_workspace)),
            patch("evo_mcp.tools.admin_tools.APIConnector", return_value=object()),
            patch("evo_mcp.tools.admin_tools.ObjectAPIClient", return_value=fake_object_client),
            patch("evo_mcp.tools.admin_tools._inspect_data_link", side_effect=fake_inspect_data_link),
            patch("evo_mcp.tools.admin_tools.evo_context", fake_evo_context),
        ):
            result = await _resolve_object_side(
                side_name="left",
                workspace_id="00000000-0000-0000-0000-000000000001",
                object_id="00000000-0000-0000-0000-000000000002",
            )

        self.assertEqual("object-1", result["object"]["id"])
        self.assertEqual("/objects/pointsets/1.0.0/pointsets.schema.json", result["object"]["schema"])
        self.assertEqual(
            [
                {"index": 1, "name": "blob-a", "id": "blob-a", "download_url": "https://example.invalid/a"},
                {"index": 2, "name": "blob-b", "id": "blob-b", "download_url": "https://example.invalid/b"},
            ],
            result["data_links"],
        )
        self.assertEqual(
            [
                {"blob_name": "blob-a", "download_url": "https://example.invalid/a", "num_rows": 3},
                {"blob_name": "blob-b", "download_url": "https://example.invalid/b", "num_rows": 3},
            ],
            result["parquet_files"],
        )

    async def test_builds_json_and_parquet_summary_report(self) -> None:
        fake_mcp = _FakeMCP()
        register_admin_tools(fake_mcp)
        compare_tool = fake_mcp.tools["compare_evo_objects_detailed"]

        async def fake_resolve_object_side(**kwargs):
            if kwargs["side_name"] == "left":
                return {
                    "instance": {"id": "instance-1", "name": "Instance One"},
                    "workspace": {"id": "workspace-1", "name": "Workspace One"},
                    "object": {
                        "id": "object-1",
                        "name": "Object One",
                        "path": "/Object One.json",
                        "version_id": "v1",
                        "schema_id": "pointsets",
                        "schema": "/objects/pointsets/1.0.0/pointsets.schema.json",
                        "schema_version": "1.0.0",
                        "created_at": None,
                        "modified_at": None,
                    },
                    "json_payload": {
                        "schema": "/objects/pointsets/1.0.0/pointsets.schema.json",
                        "crs": "EPSG:2193",
                        "properties": {"units": "m", "kind": "sample"},
                    },
                    "crs_candidates": [{"path": "$.crs", "value": "EPSG:2193"}],
                    "data_links": [
                        {"index": 1, "name": "blob-a", "id": "blob-a", "download_url": "https://example.invalid/a"},
                        {"index": 2, "name": "blob-b", "id": "blob-b", "download_url": "https://example.invalid/b"},
                    ],
                    "parquet_files": [
                        {
                            "blob_name": "blob-a",
                            "parquet_format_version": "2.6",
                            "arrow_schema": "sample_id: int32",
                            "num_rows": 3,
                            "num_row_groups": 1,
                        },
                        {
                            "blob_name": "blob-b",
                            "parquet_format_version": "2.6",
                            "arrow_schema": "label: string",
                            "num_rows": 3,
                            "num_row_groups": 1,
                        },
                    ],
                }

            return {
                "instance": {"id": "instance-2", "name": "Instance Two"},
                "workspace": {"id": "workspace-2", "name": "Workspace Two"},
                "object": {
                    "id": "object-2",
                    "name": "Object Two",
                    "path": "/Object Two.json",
                    "version_id": "v2",
                    "schema_id": "pointsets",
                    "schema": "/objects/pointsets/1.0.1/pointsets.schema.json",
                    "schema_version": "1.0.1",
                    "created_at": None,
                    "modified_at": None,
                },
                "json_payload": {
                    "schema": "/objects/pointsets/1.0.1/pointsets.schema.json",
                    "crs": "EPSG:2193",
                    "properties": {"units": "ft", "kind": "sample", "owner": "team-b"},
                },
                "crs_candidates": [{"path": "$.crs", "value": "EPSG:2193"}],
                "data_links": [
                    {"index": 1, "name": "blob-b", "id": "blob-b", "download_url": "https://example.invalid/b"},
                    {"index": 2, "name": "blob-c", "id": "blob-c", "download_url": "https://example.invalid/c"},
                ],
                "parquet_files": [
                    {
                        "blob_name": "blob-b",
                        "parquet_format_version": "2.6",
                        "arrow_schema": "label: string",
                        "num_rows": 3,
                        "num_row_groups": 1,
                    },
                    {
                        "blob_name": "blob-c",
                        "parquet_format_version": "1.0",
                        "arrow_schema": "other: int64",
                        "num_rows": 5,
                        "num_row_groups": 2,
                    },
                ],
            }

        with patch("evo_mcp.tools.admin_tools._resolve_object_side", side_effect=fake_resolve_object_side):
            result = await compare_tool(
                left_workspace_id="workspace-1",
                left_object_id="object-1",
                right_workspace_id="workspace-2",
                right_object_id="object-2",
                max_reported_differences=10,
            )

        self.assertFalse(result["summary"]["same_instance"])
        self.assertFalse(result["summary"]["same_workspace"])
        self.assertFalse(result["summary"]["same_schema"])
        self.assertFalse(result["summary"]["same_schema_version"])
        self.assertTrue(result["summary"]["same_crs_candidates"])
        self.assertEqual(1, result["summary"]["shared_blob_name_count"])
        self.assertEqual(["blob-b"], result["parquet_comparison"]["shared_blob_names"])
        self.assertEqual(["blob-a"], result["parquet_comparison"]["left_only_blob_names"])
        self.assertEqual(["blob-c"], result["parquet_comparison"]["right_only_blob_names"])
        self.assertEqual(2, result["json_comparison"]["counts"]["differing_values"])
        self.assertEqual(1, result["json_comparison"]["counts"]["right_only_paths"])
        self.assertEqual(
            {
                "blob_name": "blob-b",
                "same_parquet_format_version": True,
                "same_arrow_schema": True,
                "same_row_count": True,
                "same_row_group_count": True,
            },
            result["parquet_comparison"]["shared_blob_comparisons"][0],
        )


if __name__ == "__main__":
    unittest.main()
