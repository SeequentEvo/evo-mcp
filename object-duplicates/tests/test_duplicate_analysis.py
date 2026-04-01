from __future__ import annotations

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

import duplicate_analysis


def _user(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def _metadata(
    *,
    object_id: str,
    name: str,
    path: str,
    version_id: str,
    schema_id: str = "schema-id",
    created_by: str = "Alice",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=UUID(object_id),
        name=name,
        path=path,
        version_id=version_id,
        schema_id=schema_id,
        created_at=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc),
        created_by=_user(created_by),
        modified_at=datetime(2026, 3, 2, 12, 0, 0, tzinfo=timezone.utc),
        modified_by=_user(created_by),
    )


class _FakeObjectModel:
    def __init__(self, schema: str) -> None:
        self._schema = schema

    def model_dump(self, mode: str = "python", by_alias: bool = True) -> dict[str, str]:
        return {"schema": self._schema}


class _FakeResponse:
    def __init__(self, *, schema: str, blob_names: list[str]) -> None:
        self.object = _FakeObjectModel(schema)
        self.links = SimpleNamespace(
            data=[
                SimpleNamespace(name=blob_name, download_url=f"https://example.invalid/{blob_name}")
                for blob_name in blob_names
            ]
        )


class _FakeObjectAPIClient:
    DATA: dict[str, dict[str, object]] = {}

    def __init__(self, env, connector) -> None:  # noqa: ANN001
        self.workspace_id = str(env.workspace_id)
        self._objects_api = self

    async def list_all_objects(self, limit_per_request: int = 5000):
        return self.DATA[self.workspace_id]["objects"]

    async def get_object_by_id(
        self,
        *,
        object_id: str,
        org_id: str,
        workspace_id: str,
        version: str,
        additional_headers: dict[str, str],
    ):
        response = self.DATA[workspace_id]["responses"][object_id]
        if isinstance(response, Exception):
            raise response
        return response


class AnalyzeDuplicateObjectsTests(unittest.IsolatedAsyncioTestCase):
    async def _run_analysis(
        self,
        *,
        workspaces: list[SimpleNamespace],
        data: dict[str, dict[str, object]],
        progress_callback=None,
    ):
        _FakeObjectAPIClient.DATA = data
        with patch.object(duplicate_analysis, "ObjectAPIClient", _FakeObjectAPIClient):
            return await duplicate_analysis.analyze_duplicate_objects(
                connector=None,
                hub_url="https://hub.example.invalid",
                org_id=UUID("00000000-0000-0000-0000-0000000000aa"),
                selected_workspaces=workspaces,
                max_concurrent_object_fetches=4,
                progress_callback=progress_callback,
            )

    async def test_builds_duplicate_pair_rows_from_shared_blobs(self) -> None:
        workspace = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000001"),
            display_name="Workspace One",
        )
        object_1 = _metadata(
            object_id="00000000-0000-0000-0000-000000000101",
            name="Object One",
            path="/Object One.json",
            version_id="v1",
            created_by="Alice",
        )
        object_2 = _metadata(
            object_id="00000000-0000-0000-0000-000000000102",
            name="Object Two",
            path="/Object Two.json",
            version_id="v1",
            created_by="Bob",
        )

        result = await self._run_analysis(
            workspaces=[workspace],
            data={
                str(workspace.id): {
                    "objects": [object_1, object_2],
                    "responses": {
                        str(object_1.id): _FakeResponse(
                            schema="/objects/geological-model-meshes/1.0.1/geological-model-meshes.schema.json",
                            blob_names=["blob-a", "blob-b"],
                        ),
                        str(object_2.id): _FakeResponse(
                            schema="/objects/geological-model-meshes/1.0.1/geological-model-meshes.schema.json",
                            blob_names=["blob-b", "blob-c"],
                        ),
                    },
                }
            },
        )

        self.assertEqual(1, len(result.rows))
        row = result.rows[0]
        self.assertEqual("Workspace One", row["Object 1 Workspace"])
        self.assertEqual("Object One", row["Object 1 Name"])
        self.assertEqual("geological-model-meshes", row["Object 1 Schema"])
        self.assertEqual(1, row["Shared Blobs"])
        self.assertEqual("33.33%", row["Blob Overlap %"])

    async def test_counts_coverage_for_blobless_and_failed_objects(self) -> None:
        workspace = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000002"),
            display_name="Workspace Two",
        )
        blobless = _metadata(
            object_id="00000000-0000-0000-0000-000000000201",
            name="Blobless",
            path="/Blobless.json",
            version_id="v1",
        )
        broken = _metadata(
            object_id="00000000-0000-0000-0000-000000000202",
            name="Broken",
            path="/Broken.json",
            version_id="v1",
        )
        comparable = _metadata(
            object_id="00000000-0000-0000-0000-000000000203",
            name="Comparable",
            path="/Comparable.json",
            version_id="v1",
        )

        result = await self._run_analysis(
            workspaces=[workspace],
            data={
                str(workspace.id): {
                    "objects": [blobless, broken, comparable],
                    "responses": {
                        str(blobless.id): _FakeResponse(
                            schema="/objects/pointsets/1.0.0/pointsets.schema.json",
                            blob_names=[],
                        ),
                        str(broken.id): RuntimeError("boom"),
                        str(comparable.id): _FakeResponse(
                            schema="/objects/pointsets/1.0.0/pointsets.schema.json",
                            blob_names=["blob-a"],
                        ),
                    },
                }
            },
        )

        self.assertEqual(3, result.objects_scanned)
        self.assertEqual(1, result.objects_with_blob_refs)
        self.assertEqual(1, result.objects_without_blob_refs)
        self.assertEqual(1, result.objects_with_fetch_errors)
        self.assertEqual(0, len(result.rows))

    async def test_counts_shared_blob_once_per_object_pair(self) -> None:
        workspace = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000003"),
            display_name="Workspace Three",
        )
        object_1 = _metadata(
            object_id="00000000-0000-0000-0000-000000000301",
            name="Duplicated Blob Ref Object",
            path="/Duplicated Blob Ref Object.json",
            version_id="v1",
        )
        object_2 = _metadata(
            object_id="00000000-0000-0000-0000-000000000302",
            name="Single Blob Ref Object",
            path="/Single Blob Ref Object.json",
            version_id="v1",
        )

        result = await self._run_analysis(
            workspaces=[workspace],
            data={
                str(workspace.id): {
                    "objects": [object_1, object_2],
                    "responses": {
                        str(object_1.id): _FakeResponse(
                            schema="/objects/meshes/1.0.0/meshes.schema.json",
                            blob_names=["blob-a", "blob-a"],
                        ),
                        str(object_2.id): _FakeResponse(
                            schema="/objects/meshes/1.0.0/meshes.schema.json",
                            blob_names=["blob-a"],
                        ),
                    },
                }
            },
        )

        self.assertEqual(1, len(result.rows))
        self.assertEqual(1, result.rows[0]["Shared Blobs"])
        self.assertEqual("100.00%", result.rows[0]["Blob Overlap %"])

    async def test_reports_progress_during_object_scan(self) -> None:
        workspace = SimpleNamespace(
            id=UUID("00000000-0000-0000-0000-000000000004"),
            display_name="Workspace Four",
        )
        object_1 = _metadata(
            object_id="00000000-0000-0000-0000-000000000401",
            name="Object One",
            path="/Object One.json",
            version_id="v1",
        )
        object_2 = _metadata(
            object_id="00000000-0000-0000-0000-000000000402",
            name="Object Two",
            path="/Object Two.json",
            version_id="v1",
        )
        progress_events: list[dict[str, object]] = []

        def on_progress(event: dict[str, object]) -> None:
            progress_events.append(event)

        await self._run_analysis(
            workspaces=[workspace],
            data={
                str(workspace.id): {
                    "objects": [object_1, object_2],
                    "responses": {
                        str(object_1.id): _FakeResponse(
                            schema="/objects/pointsets/1.0.0/pointsets.schema.json",
                            blob_names=["blob-a"],
                        ),
                        str(object_2.id): _FakeResponse(
                            schema="/objects/pointsets/1.0.0/pointsets.schema.json",
                            blob_names=["blob-b"],
                        ),
                    },
                }
            },
            progress_callback=on_progress,
        )

        self.assertGreaterEqual(len(progress_events), 3)
        self.assertEqual("starting", progress_events[0]["stage"])
        scanning_events = [event for event in progress_events if event["stage"] == "scanning"]
        self.assertEqual(2, len(scanning_events))
        self.assertEqual(2, scanning_events[-1]["processed_objects"])
        self.assertEqual(2, scanning_events[-1]["total_objects"])


if __name__ == "__main__":
    unittest.main()