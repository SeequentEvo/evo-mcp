# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from evo_mcp.tools.admin_tools import register_admin_tools
from evo_mcp.tools.filesystem_tools import register_filesystem_tools
from evo_mcp.tools.general_tools import register_general_tools


class _FakeMCP:
    def __init__(self) -> None:
        self.tools: dict[str, object] = {}

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator


class ToolLoggingIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_get_workspace_returns_operation_id(self) -> None:
        fake_mcp = _FakeMCP()
        register_general_tools(fake_mcp)
        get_workspace_tool = fake_mcp.tools["get_workspace"]

        fake_workspace = SimpleNamespace(
            id="workspace-1",
            display_name="Workspace One",
            description="Example workspace",
            user_role=SimpleNamespace(name="owner"),
            created_at=None,
            updated_at=None,
            created_by=SimpleNamespace(id="user-1"),
            default_coordinate_system="EPSG:2193",
            labels=["prod"],
        )
        fake_context = SimpleNamespace(
            workspace_client=SimpleNamespace(get_workspace=AsyncMock(return_value=fake_workspace))
        )

        with (
            patch("evo_mcp.tools.general_tools.ensure_initialized", AsyncMock()),
            patch("evo_mcp.tools.general_tools.evo_context", fake_context),
        ):
            result = await get_workspace_tool(workspace_id="00000000-0000-0000-0000-000000000001", ctx=None)

        self.assertEqual("workspace-1", result["id"])
        self.assertEqual("Workspace One", result["name"])
        self.assertEqual("owner", result["user_role"])
        self.assertIn("operation_id", result)

    async def test_preview_csv_file_parse_error_returns_operation_id(self) -> None:
        fake_mcp = _FakeMCP()
        register_filesystem_tools(fake_mcp)
        preview_tool = fake_mcp.tools["preview_csv_file"]

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "broken.csv"
            csv_path.write_text("not,a,real\ncsv,for,[", encoding="utf-8")

            with patch("evo_mcp.tools.filesystem_tools.pd.read_csv", side_effect=ValueError("bad csv")):
                result = await preview_tool(file_path=str(csv_path), max_rows=5, ctx=None)

        self.assertEqual("parse_error", result["status"])
        self.assertEqual("bad csv", result["error"])
        self.assertIn("operation_id", result)

    async def test_list_my_instances_returns_serializable_dicts_with_operation_id(self) -> None:
        fake_mcp = _FakeMCP()
        register_general_tools(fake_mcp)
        list_instances_tool = fake_mcp.tools["list_my_instances"]

        fake_ctx = SimpleNamespace(info=AsyncMock())
        fake_context = SimpleNamespace(
            org_id=None,
            discovery_client=SimpleNamespace(
                list_organizations=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            id="instance-1",
                            display_name="Instance One",
                            hubs=[SimpleNamespace(url="https://hub.example.invalid")],
                        )
                    ]
                )
            ),
        )

        with (
            patch("evo_mcp.tools.general_tools.ensure_initialized", AsyncMock()),
            patch("evo_mcp.tools.general_tools.evo_context", fake_context),
        ):
            result = await list_instances_tool(ctx=fake_ctx)

        self.assertEqual(1, len(result))
        self.assertEqual("instance-1", result[0]["id"])
        self.assertEqual("Instance One", result[0]["name"])
        self.assertEqual(["https://hub.example.invalid"], result[0]["hub_urls"])
        self.assertIn("operation_id", result[0])

    async def test_list_my_instances_allows_missing_context(self) -> None:
        fake_mcp = _FakeMCP()
        register_general_tools(fake_mcp)
        list_instances_tool = fake_mcp.tools["list_my_instances"]

        fake_context = SimpleNamespace(
            org_id="instance-1",
            discovery_client=SimpleNamespace(
                list_organizations=AsyncMock(
                    return_value=[
                        SimpleNamespace(
                            id="instance-1",
                            display_name="Instance One",
                            hubs=[SimpleNamespace(url="https://hub.example.invalid")],
                        )
                    ]
                )
            ),
        )

        with (
            patch("evo_mcp.tools.general_tools.ensure_initialized", AsyncMock()),
            patch("evo_mcp.tools.general_tools.evo_context", fake_context),
        ):
            result = await list_instances_tool(ctx=None)

        self.assertEqual(1, len(result))
        self.assertEqual("instance-1", result[0]["id"])
        self.assertEqual("Instance One", result[0]["name"])
        self.assertIn("operation_id", result[0])

    async def test_workspace_copy_object_returns_operation_id(self) -> None:
        fake_mcp = _FakeMCP()
        register_admin_tools(fake_mcp)
        copy_tool = fake_mcp.tools["workspace_copy_object"]

        source_object = SimpleNamespace(
            metadata=SimpleNamespace(path="/objects/example.json"),
            as_dict=lambda: {"name": "Example"},
        )
        source_client = SimpleNamespace(
            download_object_by_id=AsyncMock(return_value=source_object),
        )
        target_client = SimpleNamespace(
            create_geoscience_object=AsyncMock(
                return_value=SimpleNamespace(
                    id="object-2",
                    name="Example",
                    path="/objects/example.json",
                    version_id="v2",
                )
            )
        )
        fake_context = SimpleNamespace(
            get_object_client=AsyncMock(side_effect=[source_client, target_client]),
            connector=object(),
        )

        with (
            patch("evo_mcp.tools.admin_tools.ensure_initialized", AsyncMock()),
            patch("evo_mcp.tools.admin_tools.evo_context", fake_context),
            patch("evo_mcp.tools.admin_tools.extract_data_references", return_value=["blob-1"]),
            patch("evo_mcp.tools.admin_tools.copy_object_data", AsyncMock()),
        ):
            result = await copy_tool(
                source_workspace_id="00000000-0000-0000-0000-000000000001",
                target_workspace_id="00000000-0000-0000-0000-000000000002",
                object_id="00000000-0000-0000-0000-000000000003",
                version="v1",
                ctx=None,
            )

        self.assertEqual("object-2", result["id"])
        self.assertEqual("Example", result["name"])
        self.assertEqual(1, result["data_blobs_copied"])
        self.assertIn("operation_id", result)

    async def test_workspace_duplicate_workspace_reports_completion_once_for_empty_selection(self) -> None:
        fake_mcp = _FakeMCP()
        register_admin_tools(fake_mcp)
        duplicate_tool = fake_mcp.tools["workspace_duplicate_workspace"]

        fake_ctx = SimpleNamespace(info=AsyncMock(), report_progress=AsyncMock())
        source_client = SimpleNamespace(list_all_objects=AsyncMock(return_value=[]))
        target_workspace = SimpleNamespace(id="workspace-2", display_name="Target Workspace")
        fake_context = SimpleNamespace(
            workspace_client=SimpleNamespace(create_workspace=AsyncMock(return_value=target_workspace)),
            get_object_client=AsyncMock(side_effect=[source_client, SimpleNamespace()]),
            connector=object(),
        )

        with (
            patch("evo_mcp.tools.admin_tools.ensure_initialized", AsyncMock()),
            patch("evo_mcp.tools.admin_tools.evo_context", fake_context),
        ):
            result = await duplicate_tool(
                source_workspace_id="00000000-0000-0000-0000-000000000001",
                target_name="Target Workspace",
                ctx=fake_ctx,
            )

        completion_calls = [
            awaited_call
            for awaited_call in fake_ctx.report_progress.await_args_list
            if awaited_call.kwargs.get("progress") == 100 and awaited_call.kwargs.get("total") == 100
        ]

        self.assertEqual(1, len(completion_calls))
        self.assertEqual("workspace-2", result["target_workspace_id"])
        self.assertEqual(0, result["objects_copied"])
        self.assertEqual(0, result["objects_failed"])


if __name__ == "__main__":
    unittest.main()