# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID

from evo_mcp.tools import duplicate_tools


def _user(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _metadata(*, object_id: str, name: str, path: str, version_id: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(object_id),
        name=name,
        path=path,
        version_id=version_id,
        schema_id="pointsets",
        created_at=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        created_by=_user("Alice"),
        modified_at=datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc),
        modified_by=_user("Alice"),
    )


class _FakePage:
    def __init__(self, *, items: list[object], offset: int, limit: int, total: int) -> None:
        self._items = items
        self.offset = offset
        self.limit = limit
        self.total = total

    def items(self) -> list[object]:
        return list(self._items)

    @property
    def next_offset(self) -> int:
        return self.offset + len(self._items)

    @property
    def is_last(self) -> bool:
        return self.next_offset >= self.total


class _FakeObjectModel:
    def __init__(self, schema: str) -> None:
        self._schema = schema

    def model_dump(self, mode: str = "python", by_alias: bool = True) -> dict[str, str]:
        return {"schema": self._schema}


class _FakeResponse:
    def __init__(self, *, schema: str, blob_names: list[str]) -> None:
        self.object = _FakeObjectModel(schema)
        self.links = SimpleNamespace(data=[SimpleNamespace(name=blob_name) for blob_name in blob_names])


class _FakeWorkspaceClient:
    def __init__(self, workspaces: list[SimpleNamespace], max_limit: int) -> None:
        self._workspaces = workspaces
        self._max_limit = max_limit
        self.calls: list[tuple[int, int]] = []

    async def list_workspaces(self, *, offset: int = 0, limit: int = 50, **_: object) -> _FakePage:
        self.calls.append((offset, limit))
        if limit > self._max_limit:
            raise RuntimeError("List pagination limit exceeded")

        items = self._workspaces[offset : offset + limit]
        return _FakePage(items=items, offset=offset, limit=limit, total=len(self._workspaces))


class _FakeObjectAPIClient:
    DATA: dict[str, dict[str, object]] = {}
    MAX_LIMIT = 50
    LIST_CALLS: list[tuple[str, int, int]] = []
    OBJECT_TIMEOUTS: list[int | float | tuple[int | float, int | float] | None] = []

    def __init__(self, env, connector) -> None:  # noqa: ANN001
        self.workspace_id = str(env.workspace_id)
        self._objects_api = self

    async def list_objects(self, *, offset: int = 0, limit: int = 5000, **_: object) -> _FakePage:
        self.LIST_CALLS.append((self.workspace_id, offset, limit))
        if limit > self.MAX_LIMIT:
            raise RuntimeError("List pagination limit exceeded")

        objects = self.DATA[self.workspace_id]["objects"]
        items = objects[offset : offset + limit]
        return _FakePage(items=items, offset=offset, limit=limit, total=len(objects))

    async def get_object_by_id(
        self,
        *,
        object_id: str,
        org_id: str,
        workspace_id: str,
        version: str,
        additional_headers: dict[str, str],
        request_timeout=None,
    ):
        del org_id, version, additional_headers
        self.OBJECT_TIMEOUTS.append(request_timeout)
        return self.DATA[workspace_id]["responses"][object_id]


class _ZeroProgressPage:
    def __init__(self, *, offset: int, limit: int, total: int) -> None:
        self.offset = offset
        self.limit = limit
        self.total = total

    def items(self) -> list[object]:
        return []

    @property
    def next_offset(self) -> int:
        return self.offset

    @property
    def is_last(self) -> bool:
        return False


class DuplicateToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_duplicate_analysis_retries_with_smaller_page_size(self) -> None:
        workspace = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            display_name="Workspace One",
        )
        object_1 = _metadata(
            object_id="00000000-0000-0000-0000-000000000101",
            name="Object One",
            path="/Object One.json",
            version_id="v1",
        )
        object_2 = _metadata(
            object_id="00000000-0000-0000-0000-000000000102",
            name="Object Two",
            path="/Object Two.json",
            version_id="v1",
        )
        object_3 = _metadata(
            object_id="00000000-0000-0000-0000-000000000103",
            name="Object Three",
            path="/Object Three.json",
            version_id="v1",
        )

        _FakeObjectAPIClient.DATA = {
            str(workspace.id): {
                "objects": [object_1, object_2, object_3],
                "responses": {
                    str(object_1.id): _FakeResponse(
                        schema="/objects/pointsets/1.0.0/pointsets.schema.json",
                        blob_names=["blob-a"],
                    ),
                    str(object_2.id): _FakeResponse(
                        schema="/objects/pointsets/1.0.0/pointsets.schema.json",
                        blob_names=["blob-a", "blob-b"],
                    ),
                    str(object_3.id): _FakeResponse(
                        schema="/objects/pointsets/1.0.0/pointsets.schema.json",
                        blob_names=["blob-c"],
                    ),
                },
            }
        }
        _FakeObjectAPIClient.LIST_CALLS = []
        _FakeObjectAPIClient.OBJECT_TIMEOUTS = []

        fake_context = SimpleNamespace(
            workspace_client=_FakeWorkspaceClient([workspace], max_limit=10),
            org_id=UUID("00000000-0000-0000-0000-0000000000aa"),
            hub_url="https://hub.example.invalid",
            connector=None,
        )

        with (
            patch.object(duplicate_tools, "ensure_initialized", AsyncMock()),
            patch.object(duplicate_tools, "evo_context", fake_context),
            patch.object(duplicate_tools, "ObjectAPIClient", _FakeObjectAPIClient),
        ):
            result = await duplicate_tools._run_duplicate_analysis(
                workspace_ids=[str(workspace.id)],
                workspace_names=None,
                max_concurrent=4,
            )

        self.assertEqual(3, result["summary"]["total_objects_scanned"])
        self.assertEqual(1, result["summary"]["duplicate_object_pairs"])
        self.assertIn((str(workspace.id), 0, duplicate_tools.DEFAULT_OBJECT_PAGE_SIZE), _FakeObjectAPIClient.LIST_CALLS)
        self.assertIn((str(workspace.id), 0, duplicate_tools.DEFAULT_OBJECT_PAGE_SIZE // 2), _FakeObjectAPIClient.LIST_CALLS)
        self.assertEqual(
            [duplicate_tools.OBJECT_FETCH_TIMEOUT_SECONDS] * 3,
            _FakeObjectAPIClient.OBJECT_TIMEOUTS,
        )

    async def test_list_all_pages_fails_fast_on_zero_progress_page(self) -> None:
        async def fetch_page(*, offset: int = 0, limit: int = 100, request_timeout=None):
            del limit, request_timeout
            return _ZeroProgressPage(offset=offset, limit=100, total=10)

        with self.assertRaisesRegex(RuntimeError, "No pagination progress while listing objects"):
            await duplicate_tools._list_all_pages(
                fetch_page,
                page_size=duplicate_tools.DEFAULT_OBJECT_PAGE_SIZE,
                resource_name="objects",
            )


if __name__ == "__main__":
    unittest.main()