# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for detailed object-to-object comparison.

This module compares two Evo objects by:
- resolving each object from the current or a specified instance/workspace
- comparing the object JSON payloads at scalar leaf paths
- downloading each linked Parquet blob and inspecting its metadata
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any
from uuid import UUID

import aiohttp
import pyarrow as pa
import pyarrow.parquet as pq
from evo.common import APIConnector
from evo.objects import ObjectAPIClient
from evo.workspaces import WorkspaceAPIClient

from evo_mcp.context import evo_context, ensure_initialized


def _normalize_schema_id(schema_id: Any) -> str | None:
    if schema_id is None:
        return None
    if hasattr(schema_id, "sub_classification"):
        return str(schema_id.sub_classification)
    return str(schema_id)


def _schema_version_from_path(schema_path: str | None) -> str | None:
    if not schema_path:
        return None
    parts = [part for part in str(schema_path).strip("/").split("/") if part]
    if len(parts) >= 4 and parts[0] == "objects":
        return parts[-2]
    return None


def _safe_value(value: Any, *, max_length: int = 240) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str) and len(value) > max_length:
            return f"{value[:max_length]}..."
        return value
    text = json.dumps(value, sort_keys=True, default=str)
    if len(text) > max_length:
        text = f"{text[:max_length]}..."
    return text


def _flatten_json(value: Any, *, path: str = "$", out: dict[str, Any] | None = None) -> dict[str, Any]:
    if out is None:
        out = {}

    if isinstance(value, dict):
        if not value:
            out[path] = {}
            return out
        for key in sorted(value):
            _flatten_json(value[key], path=f"{path}.{key}", out=out)
        return out

    if isinstance(value, list):
        if not value:
            out[path] = []
            return out
        for index, item in enumerate(value):
            _flatten_json(item, path=f"{path}[{index}]", out=out)
        return out

    out[path] = value
    return out


def _collect_crs_candidates(value: Any, *, path: str = "$", out: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    if out is None:
        out = []

    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            normalized = re.sub(r"[^a-z0-9]", "", key.lower())
            if normalized in {
                "crs",
                "coordinatecoordinatesystem",
                "coordinatereferencesystem",
                "coordinatesystem",
                "coordinatesystemname",
                "coordinatesystemwkt",
            } or normalized.endswith("crs"):
                out.append({"path": child_path, "value": _safe_value(child, max_length=500)})
            _collect_crs_candidates(child, path=child_path, out=out)
        return out

    if isinstance(value, list):
        for index, child in enumerate(value):
            _collect_crs_candidates(child, path=f"{path}[{index}]", out=out)

    return out


def _compare_json_payloads(left_payload: dict[str, Any], right_payload: dict[str, Any], *, max_differences: int) -> dict[str, Any]:
    left_flat = _flatten_json(left_payload)
    right_flat = _flatten_json(right_payload)

    left_paths = set(left_flat)
    right_paths = set(right_flat)
    shared_paths = left_paths & right_paths

    left_only_paths = sorted(left_paths - right_paths)
    right_only_paths = sorted(right_paths - left_paths)
    differing_values: list[dict[str, Any]] = []

    for path in sorted(shared_paths):
        if left_flat[path] != right_flat[path]:
            differing_values.append(
                {
                    "path": path,
                    "left": _safe_value(left_flat[path]),
                    "right": _safe_value(right_flat[path]),
                }
            )

    return {
        "counts": {
            "shared_scalar_paths": len(shared_paths),
            "left_only_paths": len(left_only_paths),
            "right_only_paths": len(right_only_paths),
            "differing_values": len(differing_values),
        },
        "left_only_paths_sample": left_only_paths[:max_differences],
        "right_only_paths_sample": right_only_paths[:max_differences],
        "different_values_sample": differing_values[:max_differences],
    }


async def _get_authorization_headers(connector: APIConnector) -> dict[str, str]:
    authorizer = getattr(connector, "_authorizer", None)
    if authorizer is None or not hasattr(authorizer, "get_default_headers"):
        return {}

    headers = await authorizer.get_default_headers()
    return {str(key): str(value) for key, value in headers.items()}


async def _download_blob_bytes(download_url: str, connector: APIConnector) -> bytes:
    headers = await _get_authorization_headers(connector)
    timeout = aiohttp.ClientTimeout(total=300)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(download_url, headers=headers) as response:
            if response.status in {401, 403} and headers:
                async with session.get(download_url) as retry_response:
                    retry_response.raise_for_status()
                    return await retry_response.read()

            response.raise_for_status()
            return await response.read()


def _parquet_schema_fields(arrow_schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
        }
        for field in arrow_schema
    ]


def _inspect_parquet_bytes(blob_name: str, blob_bytes: bytes) -> dict[str, Any]:
    parquet_file = pq.ParquetFile(pa.BufferReader(blob_bytes))
    metadata = parquet_file.metadata
    format_version = getattr(metadata, "format_version", None)

    return {
        "blob_name": blob_name,
        "size_bytes": len(blob_bytes),
        "parquet_format_version": str(format_version) if format_version is not None else None,
        "created_by": metadata.created_by,
        "num_rows": metadata.num_rows,
        "num_columns": metadata.num_columns,
        "num_row_groups": metadata.num_row_groups,
        "serialized_size": metadata.serialized_size,
        "arrow_schema": str(parquet_file.schema_arrow),
        "parquet_schema": str(parquet_file.schema),
        "fields": _parquet_schema_fields(parquet_file.schema_arrow),
    }


async def _inspect_data_link(link: dict[str, Any], connector: APIConnector) -> dict[str, Any]:
    blob_name = str(link.get("name") or link.get("id") or "unknown")
    download_url = link.get("download_url")
    result = {
        "blob_name": blob_name,
        "download_url": download_url,
    }

    if not download_url:
        result["error"] = "Missing download URL"
        return result

    try:
        blob_bytes = await _download_blob_bytes(str(download_url), connector)
        result.update(_inspect_parquet_bytes(blob_name, blob_bytes))
        return result
    except Exception as exc:
        result["error"] = str(exc)
        return result


def _compare_parquet_metadata(left_files: list[dict[str, Any]], right_files: list[dict[str, Any]]) -> dict[str, Any]:
    left_by_name = {item["blob_name"]: item for item in left_files}
    right_by_name = {item["blob_name"]: item for item in right_files}

    shared_blob_names = sorted(set(left_by_name) & set(right_by_name))
    left_only_blob_names = sorted(set(left_by_name) - set(right_by_name))
    right_only_blob_names = sorted(set(right_by_name) - set(left_by_name))

    shared_blob_comparisons = []
    for blob_name in shared_blob_names:
        left_item = left_by_name[blob_name]
        right_item = right_by_name[blob_name]
        shared_blob_comparisons.append(
            {
                "blob_name": blob_name,
                "same_parquet_format_version": left_item.get("parquet_format_version") == right_item.get("parquet_format_version"),
                "same_arrow_schema": left_item.get("arrow_schema") == right_item.get("arrow_schema"),
                "same_row_count": left_item.get("num_rows") == right_item.get("num_rows"),
                "same_row_group_count": left_item.get("num_row_groups") == right_item.get("num_row_groups"),
            }
        )

    index_pairs = []
    for index, (left_item, right_item) in enumerate(zip(left_files, right_files, strict=False), start=1):
        index_pairs.append(
            {
                "index": index,
                "left_blob_name": left_item.get("blob_name"),
                "right_blob_name": right_item.get("blob_name"),
                "same_parquet_format_version": left_item.get("parquet_format_version") == right_item.get("parquet_format_version"),
                "same_arrow_schema": left_item.get("arrow_schema") == right_item.get("arrow_schema"),
                "same_row_count": left_item.get("num_rows") == right_item.get("num_rows"),
            }
        )

    return {
        "shared_blob_names": shared_blob_names,
        "left_only_blob_names": left_only_blob_names,
        "right_only_blob_names": right_only_blob_names,
        "shared_blob_comparisons": shared_blob_comparisons,
        "index_pair_comparisons": index_pairs,
    }


async def _resolve_instance(
    *,
    instance_id: str = "",
    instance_name: str = "",
) -> dict[str, Any]:
    await ensure_initialized()

    if instance_id and instance_name:
        raise ValueError("Provide either instance_id or instance_name for each side, not both.")

    instances = await evo_context.discovery_client.list_organizations()
    if not instance_id and not instance_name:
        current_org_id = evo_context.org_id
        for instance in instances:
            if instance.id == current_org_id:
                return {
                    "id": str(instance.id),
                    "name": instance.display_name,
                    "hub_url": instance.hubs[0].url,
                }
        if current_org_id and evo_context.hub_url:
            return {
                "id": str(current_org_id),
                "name": "current_instance",
                "hub_url": evo_context.hub_url,
            }
        raise ValueError("No current Evo instance is selected.")

    for instance in instances:
        if instance_id and str(instance.id) == instance_id:
            return {
                "id": str(instance.id),
                "name": instance.display_name,
                "hub_url": instance.hubs[0].url,
            }
        if instance_name and instance.display_name == instance_name:
            return {
                "id": str(instance.id),
                "name": instance.display_name,
                "hub_url": instance.hubs[0].url,
            }

    raise ValueError(
        f"Could not resolve instance for instance_id={instance_id!r}, instance_name={instance_name!r}."
    )


async def _resolve_workspace(
    *,
    connector: APIConnector,
    org_id: str,
    workspace_id: str = "",
    workspace_name: str = "",
) -> Any:
    if workspace_id and workspace_name:
        raise ValueError("Provide either workspace_id or workspace_name for each side, not both.")
    if not workspace_id and not workspace_name:
        raise ValueError("Each side must include workspace_id or workspace_name.")

    workspace_client = WorkspaceAPIClient(connector, UUID(org_id))
    if workspace_id:
        return await workspace_client.get_workspace(UUID(workspace_id))

    workspaces = await workspace_client.list_workspaces(name=workspace_name, limit=200)
    exact_matches = [workspace for workspace in workspaces.items() if workspace.display_name == workspace_name]
    if not exact_matches:
        raise ValueError(f"Workspace '{workspace_name}' was not found in instance {org_id}.")
    return exact_matches[0]


async def _resolve_object_side(
    *,
    side_name: str,
    instance_id: str = "",
    instance_name: str = "",
    workspace_id: str = "",
    workspace_name: str = "",
    object_id: str = "",
    object_path: str = "",
    version: str = "",
) -> dict[str, Any]:
    if object_id and object_path:
        raise ValueError(f"Provide either {side_name}_object_id or {side_name}_object_path, not both.")
    if not object_id and not object_path:
        raise ValueError(f"Each side must include {side_name}_object_id or {side_name}_object_path.")

    instance = await _resolve_instance(instance_id=instance_id, instance_name=instance_name)
    connector = APIConnector(
        instance["hub_url"],
        evo_context.connector._transport,
        evo_context.connector._authorizer,
    )
    workspace = await _resolve_workspace(
        connector=connector,
        org_id=instance["id"],
        workspace_id=workspace_id,
        workspace_name=workspace_name,
    )

    object_client = ObjectAPIClient(workspace.get_environment(), connector)
    requested_version = version or None

    if object_id:
        downloaded = await object_client.download_object_by_id(UUID(object_id), version=requested_version)
    else:
        downloaded = await object_client.download_object_by_path(object_path, version=requested_version)

    metadata = downloaded.metadata
    response = await object_client._objects_api.get_object_by_id(
        object_id=str(metadata.id),
        org_id=instance["id"],
        workspace_id=str(workspace.id),
        version=metadata.version_id,
        additional_headers={"Accept-Encoding": "gzip"},
    )

    object_payload = response.object.model_dump(mode="python", by_alias=True)
    data_links = []
    for index, link in enumerate(getattr(getattr(response, "links", None), "data", []) or [], start=1):
        data_links.append(
            {
                "index": index,
                "name": str(getattr(link, "name", getattr(link, "id", f"blob-{index}"))),
                "id": str(getattr(link, "id", "") or ""),
                "download_url": getattr(link, "download_url", None),
            }
        )

    parquet_files = await asyncio.gather(*[_inspect_data_link(link, connector) for link in data_links])
    schema_path = object_payload.get("schema")

    return {
        "side": side_name,
        "instance": {
            "id": instance["id"],
            "name": instance["name"],
        },
        "workspace": {
            "id": str(workspace.id),
            "name": workspace.display_name,
        },
        "object": {
            "id": str(metadata.id),
            "name": metadata.name,
            "path": metadata.path,
            "version_id": metadata.version_id,
            "schema_id": _normalize_schema_id(metadata.schema_id),
            "schema": schema_path,
            "schema_version": _schema_version_from_path(schema_path),
            "created_at": metadata.created_at,
            "modified_at": metadata.modified_at,
        },
        "json_payload": object_payload,
        "crs_candidates": _collect_crs_candidates(object_payload),
        "data_links": data_links,
        "parquet_files": parquet_files,
    }


def register_object_compare_tools(mcp):
    """Register detailed object comparison tools with the FastMCP server."""

    @mcp.tool()
    async def compare_evo_objects_detailed(
        left_workspace_id: str = "",
        left_workspace_name: str = "",
        left_object_id: str = "",
        left_object_path: str = "",
        left_version: str = "",
        left_instance_id: str = "",
        left_instance_name: str = "",
        right_workspace_id: str = "",
        right_workspace_name: str = "",
        right_object_id: str = "",
        right_object_path: str = "",
        right_version: str = "",
        right_instance_id: str = "",
        right_instance_name: str = "",
        max_reported_differences: int = 25,
    ) -> dict:
        """Compare two Evo objects in detail, including linked Parquet metadata.

        Each side can point to either the current instance or a specific alternate
        instance. The tool resolves the object, compares its JSON payload, then
        downloads each linked Parquet blob from `links.data` and reports schema and
        format metadata.

        Args:
            left_workspace_id: Left-side workspace UUID.
            left_workspace_name: Left-side workspace display name.
            left_object_id: Left-side object UUID.
            left_object_path: Left-side object path.
            left_version: Optional left-side object version.
            left_instance_id: Optional left-side instance UUID.
            left_instance_name: Optional left-side instance display name.
            right_workspace_id: Right-side workspace UUID.
            right_workspace_name: Right-side workspace display name.
            right_object_id: Right-side object UUID.
            right_object_path: Right-side object path.
            right_version: Optional right-side object version.
            right_instance_id: Optional right-side instance UUID.
            right_instance_name: Optional right-side instance display name.
            max_reported_differences: Max JSON diff items returned in samples.

        Returns:
            A detailed comparison report with object summaries, JSON differences,
            and Parquet metadata for each linked data blob.
        """
        if max_reported_differences < 1:
            raise ValueError("max_reported_differences must be at least 1")

        left_side, right_side = await asyncio.gather(
            _resolve_object_side(
                side_name="left",
                instance_id=left_instance_id,
                instance_name=left_instance_name,
                workspace_id=left_workspace_id,
                workspace_name=left_workspace_name,
                object_id=left_object_id,
                object_path=left_object_path,
                version=left_version,
            ),
            _resolve_object_side(
                side_name="right",
                instance_id=right_instance_id,
                instance_name=right_instance_name,
                workspace_id=right_workspace_id,
                workspace_name=right_workspace_name,
                object_id=right_object_id,
                object_path=right_object_path,
                version=right_version,
            ),
        )

        left_crs_values = [entry["value"] for entry in left_side["crs_candidates"]]
        right_crs_values = [entry["value"] for entry in right_side["crs_candidates"]]
        parquet_comparison = _compare_parquet_metadata(left_side["parquet_files"], right_side["parquet_files"])

        return {
            "summary": {
                "same_instance": left_side["instance"]["id"] == right_side["instance"]["id"],
                "same_workspace": left_side["workspace"]["id"] == right_side["workspace"]["id"],
                "same_schema": left_side["object"]["schema"] == right_side["object"]["schema"],
                "same_schema_id": left_side["object"]["schema_id"] == right_side["object"]["schema_id"],
                "same_schema_version": left_side["object"]["schema_version"] == right_side["object"]["schema_version"],
                "same_crs_candidates": left_crs_values == right_crs_values,
                "left_data_link_count": len(left_side["data_links"]),
                "right_data_link_count": len(right_side["data_links"]),
                "shared_blob_name_count": len(parquet_comparison["shared_blob_names"]),
                "left_only_blob_name_count": len(parquet_comparison["left_only_blob_names"]),
                "right_only_blob_name_count": len(parquet_comparison["right_only_blob_names"]),
            },
            "left_object": {
                "instance": left_side["instance"],
                "workspace": left_side["workspace"],
                "object": left_side["object"],
                "crs_candidates": left_side["crs_candidates"],
                "data_links": left_side["data_links"],
                "parquet_files": left_side["parquet_files"],
            },
            "right_object": {
                "instance": right_side["instance"],
                "workspace": right_side["workspace"],
                "object": right_side["object"],
                "crs_candidates": right_side["crs_candidates"],
                "data_links": right_side["data_links"],
                "parquet_files": right_side["parquet_files"],
            },
            "json_comparison": _compare_json_payloads(
                left_side["json_payload"],
                right_side["json_payload"],
                max_differences=max_reported_differences,
            ),
            "parquet_comparison": parquet_comparison,
        }