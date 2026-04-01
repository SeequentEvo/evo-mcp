from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Awaitable, Callable
from uuid import UUID

from evo.common.data import Environment
from evo.common import APIConnector
from evo.objects import ObjectAPIClient
from evo.workspaces import Workspace


ProgressCallback = Callable[[dict[str, Any]], None | Awaitable[None]]


def _fmt_user(user: Any) -> str:
    if user is None:
        return "unknown"
    return (
        getattr(user, "name", None)
        or getattr(user, "display_name", None)
        or getattr(user, "id", None)
        or "unknown"
    )


def _fmt_dt(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%d/%m/%Y")
    return str(value)


def _fmt_pct(part: int, whole: int) -> str:
    if not whole:
        return "0.00%"
    return f"{(part / whole) * 100:.2f}%"


def _fmt_overlap_pct(shared: int, left_total: int, right_total: int) -> str:
    union = left_total + right_total - shared
    if union <= 0:
        return "0.00%"
    return _fmt_pct(shared, union)


def _parse_pct(value: str) -> float:
    return float(value.rstrip("%")) if value.endswith("%") else float(value)


def _clean_object_name(ref: dict[str, Any]) -> str:
    object_name = ref.get("object_name") or ref.get("object_path") or ""
    object_name = object_name.lstrip("/")
    if object_name.endswith(".json"):
        object_name = object_name[:-5]
    return object_name


def _fmt_object_schema(ref: dict[str, Any]) -> str:
    schema = str(ref.get("schema") or "").strip()
    if schema:
        schema_parts = [part for part in schema.strip("/").split("/") if part]
        if len(schema_parts) >= 2 and schema_parts[0] == "objects":
            return schema_parts[1]

        schema_name = schema_parts[-1] if schema_parts else schema
        if schema_name.endswith(".schema.json"):
            return schema_name[: -len(".schema.json")]
        if schema_name.endswith(".json"):
            return schema_name[: -len(".json")]
        return schema_name

    schema_id = str(ref.get("schema_id") or "").strip()
    if not schema_id:
        return "unknown"

    normalized = schema_id.rstrip("/")
    for separator in ("/", ":"):
        if separator in normalized:
            normalized = normalized.split(separator)[-1]

    return normalized or schema_id


@dataclass(slots=True)
class AnalysisResult:
    workspace_scan: dict[str, dict[str, Any]]
    object_lookup: dict[tuple[str, str], dict[str, Any]]
    object_blob_counts: dict[tuple[str, str], int]
    object_pair_duplicate_counts: dict[tuple[tuple[str, str], tuple[str, str]], int]
    object_download_errors: list[dict[str, Any]]
    duplicate_blob_hash_count: int
    rows: list[dict[str, Any]]

    @property
    def workspaces_scanned(self) -> int:
        return len(self.workspace_scan)

    @property
    def objects_scanned(self) -> int:
        return sum(workspace["object_count"] for workspace in self.workspace_scan.values())

    def _iter_scanned_objects(self):
        for workspace in self.workspace_scan.values():
            yield from workspace["objects"]

    @property
    def objects_with_blob_refs(self) -> int:
        return sum(1 for obj in self._iter_scanned_objects() if obj.get("data_links"))

    @property
    def objects_without_blob_refs(self) -> int:
        return sum(
            1
            for obj in self._iter_scanned_objects()
            if not obj.get("scan_error") and not obj.get("data_links")
        )

    @property
    def objects_with_fetch_errors(self) -> int:
        return sum(1 for obj in self._iter_scanned_objects() if obj.get("scan_error"))

    @property
    def unique_blob_hashes(self) -> int:
        return len(
            {
                link["name"]
                for workspace in self.workspace_scan.values()
                for obj in workspace["objects"]
                for link in obj.get("data_links", [])
            }
        )

    def sorted_rows(self) -> list[dict[str, Any]]:
        return sorted(
            self.rows,
            key=lambda row: (
                -_parse_pct(row["Blob Overlap %"]),
                -row["Shared Blobs"],
                row["Object 1 Workspace"],
                row["Object 1 Name"],
                row["Object 2 Workspace"],
                row["Object 2 Name"],
            ),
        )

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame(self.sorted_rows()).reset_index(drop=True)


@dataclass(slots=True)
class _ScannedObjectResult:
    object_key: tuple[str, str]
    object_record: dict[str, Any]
    blob_refs: list[tuple[str, dict[str, Any]]]
    unique_blob_count: int
    error: str | None = None


async def _emit_progress(progress_callback: ProgressCallback | None, payload: dict[str, Any]) -> None:
    if progress_callback is None:
        return

    maybe_awaitable = progress_callback(payload)
    if asyncio.iscoroutine(maybe_awaitable):
        await maybe_awaitable


async def _scan_object_details(
    *,
    object_client: ObjectAPIClient,
    org_id: UUID,
    workspace: Workspace,
    workspace_name: str,
    object_metadata: Any,
    semaphore: asyncio.Semaphore,
    on_complete: Callable[[bool, str], Awaitable[None]] | None = None,
) -> _ScannedObjectResult:
    object_key = (str(workspace.id), str(object_metadata.id))
    object_record = {
        "object_id": str(object_metadata.id),
        "object_name": object_metadata.name,
        "object_path": object_metadata.path,
        "version_id": object_metadata.version_id,
        "schema_id": str(object_metadata.schema_id),
        "scan_error": None,
        "created_at": _fmt_dt(getattr(object_metadata, "created_at", None)),
        "created_by": _fmt_user(getattr(object_metadata, "created_by", None)),
        "updated_at": _fmt_dt(getattr(object_metadata, "modified_at", None)),
        "updated_by": _fmt_user(getattr(object_metadata, "modified_by", None)),
        "data_hashes": [],
        "data_links": [],
    }

    async with semaphore:
        try:
            response = await object_client._objects_api.get_object_by_id(
                object_id=str(object_metadata.id),
                org_id=str(org_id),
                workspace_id=str(workspace.id),
                version=object_metadata.version_id,
                additional_headers={"Accept-Encoding": "gzip"},
            )

            object_record["object_json"] = response.object.model_dump(mode="python", by_alias=True)
            object_record["schema"] = object_record["object_json"].get("schema")
            blob_refs: list[tuple[str, dict[str, Any]]] = []

            for link in getattr(getattr(response, "links", None), "data", []) or []:
                blob_hash = str(getattr(link, "name", getattr(link, "id", "")))
                download_url = getattr(link, "download_url", None)

                if not blob_hash:
                    continue

                object_record["data_hashes"].append(blob_hash)
                object_record["data_links"].append({"name": blob_hash, "download": download_url})

                blob_refs.append(
                    (
                        blob_hash,
                        {
                            "workspace_id": str(workspace.id),
                            "workspace_name": workspace_name,
                            "object_id": str(object_metadata.id),
                            "object_name": object_metadata.name,
                            "object_path": object_metadata.path,
                            "version_id": object_metadata.version_id,
                            "schema": object_record.get("schema"),
                            "schema_id": str(object_metadata.schema_id),
                            "created_at": _fmt_dt(getattr(object_metadata, "created_at", None)),
                            "created_by": _fmt_user(getattr(object_metadata, "created_by", None)),
                            "updated_at": _fmt_dt(getattr(object_metadata, "modified_at", None)),
                            "updated_by": _fmt_user(getattr(object_metadata, "modified_by", None)),
                            "download": download_url,
                        },
                    )
                )

            object_record["data_hashes"].sort()
            if on_complete is not None:
                await on_complete(False, object_metadata.name)
            return _ScannedObjectResult(
                object_key=object_key,
                object_record=object_record,
                blob_refs=blob_refs,
                unique_blob_count=len(set(object_record["data_hashes"])),
            )
        except Exception as exc:
            object_record["scan_error"] = str(exc)
            if on_complete is not None:
                await on_complete(True, object_metadata.name)
            return _ScannedObjectResult(
                object_key=object_key,
                object_record=object_record,
                blob_refs=[],
                unique_blob_count=0,
                error=str(exc),
            )


async def analyze_duplicate_objects(
    *,
    connector: APIConnector,
    hub_url: str,
    org_id: UUID,
    selected_workspaces: list[Workspace],
    max_concurrent_object_fetches: int = 20,
    progress_callback: ProgressCallback | None = None,
) -> AnalysisResult:
    workspace_scan: dict[str, dict[str, Any]] = {}
    blob_index: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    object_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    object_blob_counts: dict[tuple[str, str], int] = {}
    object_download_errors: list[dict[str, Any]] = []
    semaphore = asyncio.Semaphore(max(1, max_concurrent_object_fetches))
    workspace_objects: list[tuple[Workspace, str, ObjectAPIClient, list[Any]]] = []

    for workspace in selected_workspaces:
        workspace_name = workspace.display_name or str(workspace.id)
        workspace_env = Environment(
            hub_url=hub_url,
            org_id=org_id,
            workspace_id=workspace.id,
        )
        object_client = ObjectAPIClient(workspace_env, connector)
        objects = await object_client.list_all_objects(limit_per_request=5000)
        workspace_objects.append((workspace, workspace_name, object_client, objects))

    total_objects = sum(len(objects) for _, _, _, objects in workspace_objects)
    processed_objects = 0
    progress_lock = asyncio.Lock()

    await _emit_progress(
        progress_callback,
        {
            "stage": "starting",
            "processed_objects": 0,
            "total_objects": total_objects,
        },
    )

    async def on_object_complete(has_error: bool, object_name: str, workspace_name: str) -> None:
        nonlocal processed_objects
        async with progress_lock:
            processed_objects += 1
            await _emit_progress(
                progress_callback,
                {
                    "stage": "scanning",
                    "processed_objects": processed_objects,
                    "total_objects": total_objects,
                    "workspace_name": workspace_name,
                    "object_name": object_name,
                    "has_error": has_error,
                },
            )

    for workspace, workspace_name, object_client, objects in workspace_objects:

        workspace_scan[str(workspace.id)] = {
            "workspace_name": workspace_name,
            "workspace_id": str(workspace.id),
            "object_count": len(objects),
            "objects": [],
        }

        scanned_objects = await asyncio.gather(
            *[
                _scan_object_details(
                    object_client=object_client,
                    org_id=org_id,
                    workspace=workspace,
                    workspace_name=workspace_name,
                    object_metadata=object_metadata,
                    semaphore=semaphore,
                    on_complete=lambda has_error, object_name, workspace_name=workspace_name: on_object_complete(
                        has_error,
                        object_name,
                        workspace_name,
                    ),
                )
                for object_metadata in objects
            ]
        )

        for scanned_object in scanned_objects:
            object_blob_counts[scanned_object.object_key] = scanned_object.unique_blob_count
            for blob_hash, ref in scanned_object.blob_refs:
                blob_index[blob_hash].append(ref)
                object_lookup[scanned_object.object_key] = ref

            if scanned_object.error is not None:
                workspace_scan[str(workspace.id)]["objects"].append(scanned_object.object_record)
                object_download_errors.append(
                    {
                        "workspace_id": str(workspace.id),
                        "workspace_name": workspace_name,
                        "object_id": scanned_object.object_record["object_id"],
                        "object_path": scanned_object.object_record["object_path"],
                        "error": scanned_object.error,
                    }
                )
                continue

            workspace_scan[str(workspace.id)]["objects"].append(scanned_object.object_record)

    object_pair_duplicate_counts: defaultdict[tuple[tuple[str, str], tuple[str, str]], int] = defaultdict(int)

    for refs in blob_index.values():
        per_hash_objects: dict[tuple[str | None, str | None], dict[str, Any]] = {}
        for ref in refs:
            key = (ref.get("workspace_id"), ref.get("object_id"))
            if key not in per_hash_objects:
                per_hash_objects[key] = ref

        if len(per_hash_objects) < 2:
            continue

        for left_key, right_key in combinations(sorted(per_hash_objects.keys()), 2):
            object_pair_duplicate_counts[(left_key, right_key)] += 1

    duplicate_blob_hash_count = sum(1 for refs in blob_index.values() if len(refs) > 1)
    rows: list[dict[str, Any]] = []

    for (left_key, right_key), duplicate_count in sorted(
        object_pair_duplicate_counts.items(),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    ):
        left_ref = object_lookup.get(left_key, {})
        right_ref = object_lookup.get(right_key, {})
        left_total_blobs = object_blob_counts.get(left_key, 0)
        right_total_blobs = object_blob_counts.get(right_key, 0)
        rows.append(
            {
                "Object 1 Workspace": left_ref.get("workspace_name", "unknown"),
                "Object 1 Name": _clean_object_name(left_ref),
                "Object 1 Schema": _fmt_object_schema(left_ref),
                "Object 1 Blobs": left_total_blobs,
                "Object 1 Created By": left_ref.get("created_by", "unknown"),
                "Object 1 Created At": left_ref.get("created_at", "unknown"),
                "Object 2 Workspace": right_ref.get("workspace_name", "unknown"),
                "Object 2 Name": _clean_object_name(right_ref),
                "Object 2 Schema": _fmt_object_schema(right_ref),
                "Object 2 Blobs": right_total_blobs,
                "Object 2 Created By": right_ref.get("created_by", "unknown"),
                "Object 2 Created At": right_ref.get("created_at", "unknown"),
                "Shared Blobs": duplicate_count,
                "Blob Overlap %": _fmt_overlap_pct(duplicate_count, left_total_blobs, right_total_blobs),
            }
        )

    return AnalysisResult(
        workspace_scan=workspace_scan,
        object_lookup=object_lookup,
        object_blob_counts=object_blob_counts,
        object_pair_duplicate_counts=dict(object_pair_duplicate_counts),
        object_download_errors=object_download_errors,
        duplicate_blob_hash_count=duplicate_blob_hash_count,
        rows=rows,
    )


from duplicate_analysis_rendering import build_analysis_result_widget, render_analysis_result