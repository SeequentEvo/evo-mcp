# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for workspace management and cross-workspace analysis operations.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations
from typing import Any, Awaitable, Callable
from urllib.parse import urlparse
from uuid import UUID

import aiohttp
import pyarrow as pa
import pyarrow.parquet as pq
from evo.common import APIConnector
from evo.common.data import Environment
from evo.objects import ObjectAPIClient
from evo.workspaces import WorkspaceAPIClient
from fastmcp import Context

from evo_mcp.context import ensure_initialized, evo_context
from evo_mcp.utils.downloaded_object_utils import downloaded_object_data_links
from evo_mcp.utils.evo_data_utils import copy_object_data, extract_data_references

logger = logging.getLogger(__name__)

DEFAULT_WORKSPACE_PAGE_SIZE = 100
DEFAULT_OBJECT_PAGE_SIZE = 100
DEFAULT_MAX_WORKSPACES = 10
MIN_PAGE_SIZE = 1
LIST_REQUEST_TIMEOUT_SECONDS = 60
OBJECT_FETCH_TIMEOUT_SECONDS = 60
PARQUET_INSPECTION_MAX_CONCURRENCY = 10
PARQUET_MAGIC = b"PAR1"
PARQUET_FOOTER_SIZE = 8
MAX_PARQUET_METADATA_BYTES = 64 * 1024 * 1024  # 64 MB safety cap
MAX_FULL_BLOB_DOWNLOAD_BYTES = 256 * 1024 * 1024  # 256 MB safety cap for full-blob fallback


def _is_pagination_limit_error(exc: Exception) -> bool:
    return "pagination limit exceeded" in str(exc).lower()


def _supports_request_timeout(fetch_page: Callable[..., Awaitable[Any]]) -> bool:
    try:
        signature = inspect.signature(fetch_page)
    except (TypeError, ValueError):
        return True

    for parameter in signature.parameters.values():
        if parameter.kind == inspect.Parameter.VAR_KEYWORD:
            return True

    return "request_timeout" in signature.parameters


async def _list_all_pages(
    fetch_page: Callable[..., Awaitable[Any]],
    *,
    page_size: int,
    resource_name: str,
) -> list[Any]:
    current_page_size = max(MIN_PAGE_SIZE, page_size)
    supports_request_timeout = _supports_request_timeout(fetch_page)

    while True:
        items: list[Any] = []
        offset = 0

        try:
            while True:
                fetch_kwargs = {
                    "offset": offset,
                    "limit": current_page_size,
                }
                if supports_request_timeout:
                    fetch_kwargs["request_timeout"] = LIST_REQUEST_TIMEOUT_SECONDS

                page = await fetch_page(**fetch_kwargs)
                page_items = page.items()
                next_offset = page.next_offset

                if next_offset <= offset and not page.is_last:
                    raise RuntimeError(
                        f"No pagination progress while listing {resource_name}: "
                        f"offset={offset}, limit={current_page_size}, total={page.total}"
                    )

                items.extend(page_items)
                if page.is_last:
                    return items
                offset = next_offset
        except Exception as exc:
            if not _is_pagination_limit_error(exc) or current_page_size <= MIN_PAGE_SIZE:
                raise

            next_page_size = max(MIN_PAGE_SIZE, current_page_size // 2)
            if next_page_size == current_page_size:
                raise

            logger.warning(
                "List pagination limit exceeded while listing %s with limit=%s; retrying with limit=%s",
                resource_name,
                current_page_size,
                next_page_size,
            )
            current_page_size = next_page_size


def _fmt_user(user: Any) -> str:
    if user is None:
        return "unknown"
    return str(
        getattr(user, "name", None) or getattr(user, "display_name", None) or getattr(user, "id", None) or "unknown"
    )


def _fmt_dt(value: Any) -> str:
    if value is None:
        return "unknown"
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    return str(value)


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


def _fmt_overlap_pct(shared: int, left_total: int, right_total: int) -> str:
    union = left_total + right_total - shared
    if union <= 0:
        return "0.00%"
    return f"{(shared / union) * 100:.2f}%"


def _parse_pct(value: str) -> float:
    return float(value.rstrip("%")) if value.endswith("%") else float(value)


async def _scan_object(
    *,
    object_client: ObjectAPIClient,
    workspace_id: UUID,
    workspace_name: str,
    object_metadata: Any,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "workspace_id": str(workspace_id),
        "workspace_name": workspace_name,
        "object_id": str(object_metadata.id),
        "object_name": object_metadata.name,
        "object_path": object_metadata.path,
        "version_id": object_metadata.version_id,
        "schema_id": _normalize_schema_id(object_metadata.schema_id),
        "created_at": _fmt_dt(getattr(object_metadata, "created_at", None)),
        "created_by": _fmt_user(getattr(object_metadata, "created_by", None)),
        "updated_at": _fmt_dt(getattr(object_metadata, "modified_at", None)),
        "updated_by": _fmt_user(getattr(object_metadata, "modified_by", None)),
        "blob_names": [],
        "scan_error": None,
    }

    async with semaphore:
        try:
            downloaded = await object_client.download_object_by_id(
                UUID(str(object_metadata.id)),
                version=object_metadata.version_id,
                request_timeout=OBJECT_FETCH_TIMEOUT_SECONDS,
            )

            record["schema"] = downloaded.as_dict().get("schema")
            record["blob_names"] = [link["name"] for link in downloaded_object_data_links(downloaded)]
        except Exception as exc:
            record["scan_error"] = str(exc)

    return record


async def _preview_workspaces() -> list[dict[str, Any]]:
    """Return a lightweight list of workspaces with object counts (no downloads)."""
    await ensure_initialized()

    ws_list = await _list_all_pages(
        evo_context.workspace_client.list_workspaces,
        page_size=DEFAULT_WORKSPACE_PAGE_SIZE,
        resource_name="workspaces",
    )

    hub_url = evo_context.hub_url
    org_id = evo_context.org_id
    results: list[dict[str, Any]] = []

    for workspace in ws_list:
        ws_name = workspace.display_name or str(workspace.id)
        ws_env = Environment(hub_url=hub_url, org_id=org_id, workspace_id=workspace.id)
        object_client = ObjectAPIClient(ws_env, evo_context.connector)
        try:
            page = await object_client.list_objects(offset=0, limit=1)
            object_count = page.total if page.total is not None else len(page.items())
        except Exception as exc:
            logger.warning("Failed to list objects in workspace %s: %s", ws_name, exc)
            object_count = -1
        results.append(
            {
                "workspace_id": str(workspace.id),
                "workspace_name": ws_name,
                "object_count": object_count,
            }
        )

    return results


async def _report_progress(
    ctx: Context | None,
    progress: float,
    total: float | None = None,
    message: str | None = None,
) -> None:
    if ctx is None:
        return
    try:
        await ctx.report_progress(progress, total, message)
    except Exception:
        pass


async def _run_duplicate_analysis(
    workspace_ids: list[str] | None,
    workspace_names: list[str] | None,
    max_concurrent: int,
    max_workspaces: int = DEFAULT_MAX_WORKSPACES,
    scan_all_workspaces: bool = False,
    ctx: Context | None = None,
) -> dict[str, Any]:
    await ensure_initialized()

    ws_list = await _list_all_pages(
        evo_context.workspace_client.list_workspaces,
        page_size=DEFAULT_WORKSPACE_PAGE_SIZE,
        resource_name="workspaces",
    )

    if workspace_ids:
        requested = {wid.lower() for wid in workspace_ids}
        ws_list = [ws for ws in ws_list if str(ws.id).lower() in requested]
        if not ws_list:
            return {"error": "None of the provided workspace IDs matched available workspaces."}
    elif workspace_names:
        requested = {n.lower() for n in workspace_names}
        ws_list = [ws for ws in ws_list if (ws.display_name or "").lower() in requested]
        if not ws_list:
            return {"error": "None of the provided workspace names matched available workspaces."}
    elif not scan_all_workspaces and len(ws_list) > max_workspaces:
        return {
            "error": (
                f"This instance has {len(ws_list)} workspaces which exceeds the "
                f"max_workspaces limit of {max_workspaces}. Scanning all of them "
                f"would be very slow. Either specify workspace_ids or "
                f"workspace_names to narrow the scan, increase max_workspaces, "
                f"or set scan_all_workspaces=True to override this safety limit."
            ),
            "available_workspaces": [
                {
                    "workspace_id": str(ws.id),
                    "workspace_name": ws.display_name or str(ws.id),
                }
                for ws in ws_list
            ],
            "total_workspaces": len(ws_list),
            "max_workspaces": max_workspaces,
        }

    org_id = evo_context.org_id
    hub_url = evo_context.hub_url
    semaphore = asyncio.Semaphore(max(1, max_concurrent))

    blob_index: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    object_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    object_blob_counts: dict[tuple[str, str], int] = {}
    workspace_stats: list[dict[str, Any]] = []
    total_objects = 0
    total_errors = 0
    objects_with_blobs = 0
    objects_without_blobs = 0
    processed_workspaces = 0
    total_workspace_count = len(ws_list)

    await _report_progress(ctx, 0, total_workspace_count, f"Scanning {total_workspace_count} workspace(s)...")

    for workspace in ws_list:
        ws_name = workspace.display_name or str(workspace.id)
        ws_env = Environment(hub_url=hub_url, org_id=org_id, workspace_id=workspace.id)
        object_client = ObjectAPIClient(ws_env, evo_context.connector)

        try:
            objects = await _list_all_pages(
                object_client.list_objects,
                page_size=DEFAULT_OBJECT_PAGE_SIZE,
                resource_name=f"objects in workspace {ws_name}",
            )
        except Exception as exc:
            logger.warning("Failed to list objects in workspace %s: %s", ws_name, exc)
            workspace_stats.append({"name": ws_name, "id": str(workspace.id), "objects": 0, "error": str(exc)})
            processed_workspaces += 1
            await _report_progress(
                ctx,
                processed_workspaces,
                total_workspace_count,
                f"Failed to scan workspace {ws_name}: {exc} \u2014 "
                f"{processed_workspaces}/{total_workspace_count} workspaces done",
            )
            continue

        batch_size = max(1, max_concurrent)
        scanned: list[dict[str, Any]] = []
        for i in range(0, len(objects), batch_size):
            batch = objects[i : i + batch_size]
            batch_results = await asyncio.gather(
                *[
                    _scan_object(
                        object_client=object_client,
                        workspace_id=workspace.id,
                        workspace_name=ws_name,
                        object_metadata=obj,
                        semaphore=semaphore,
                    )
                    for obj in batch
                ]
            )
            scanned.extend(batch_results)

        ws_object_count = len(scanned)
        ws_error_count = sum(1 for result in scanned if result["scan_error"])
        total_objects += ws_object_count
        total_errors += ws_error_count
        workspace_stats.append(
            {"name": ws_name, "id": str(workspace.id), "objects": ws_object_count, "errors": ws_error_count}
        )

        processed_workspaces += 1
        await _report_progress(
            ctx,
            processed_workspaces,
            total_workspace_count,
            f"Scanned workspace {ws_name} ({ws_object_count} objects) — "
            f"{processed_workspaces}/{total_workspace_count} workspaces done",
        )

        for record in scanned:
            obj_key = (record["workspace_id"], record["object_id"])
            unique_blobs = set(record["blob_names"])
            object_blob_counts[obj_key] = len(unique_blobs)

            if record["scan_error"]:
                continue

            if unique_blobs:
                objects_with_blobs += 1
            else:
                objects_without_blobs += 1

            for blob_hash in unique_blobs:
                ref = {
                    "workspace_id": record["workspace_id"],
                    "workspace_name": record["workspace_name"],
                    "object_id": record["object_id"],
                    "object_name": record["object_name"],
                    "object_path": record["object_path"],
                    "version_id": record["version_id"],
                    "schema": record.get("schema"),
                    "schema_id": record["schema_id"],
                    "created_at": record["created_at"],
                    "created_by": record["created_by"],
                }
                blob_index[blob_hash].append(ref)
                object_lookup[obj_key] = ref

    pair_counts: defaultdict[tuple[tuple[str, str], tuple[str, str]], int] = defaultdict(int)
    for refs in blob_index.values():
        per_hash: dict[tuple[str, str], dict[str, Any]] = {}
        for ref in refs:
            key = (ref["workspace_id"], ref["object_id"])
            if key not in per_hash:
                per_hash[key] = ref
        if len(per_hash) < 2:
            continue
        for left, right in combinations(sorted(per_hash.keys()), 2):
            pair_counts[(left, right)] += 1

    duplicate_blob_count = sum(1 for refs in blob_index.values() if len(refs) > 1)
    unique_blob_count = len(blob_index)

    rows: list[dict[str, Any]] = []
    for (left_key, right_key), shared in sorted(pair_counts.items(), key=lambda item: (-item[1], item[0])):
        left = object_lookup.get(left_key, {})
        right = object_lookup.get(right_key, {})
        left_total = object_blob_counts.get(left_key, 0)
        right_total = object_blob_counts.get(right_key, 0)
        rows.append(
            {
                "object_1_workspace": left.get("workspace_name", "unknown"),
                "object_1_workspace_id": left.get("workspace_id", ""),
                "object_1_name": _clean_object_name(left),
                "object_1_id": left.get("object_id", ""),
                "object_1_path": left.get("object_path", ""),
                "object_1_version_id": left.get("version_id", ""),
                "object_1_schema": _fmt_object_schema(left),
                "object_1_blobs": left_total,
                "object_1_created_by": left.get("created_by", "unknown"),
                "object_1_created_at": left.get("created_at", "unknown"),
                "object_2_workspace": right.get("workspace_name", "unknown"),
                "object_2_workspace_id": right.get("workspace_id", ""),
                "object_2_name": _clean_object_name(right),
                "object_2_id": right.get("object_id", ""),
                "object_2_path": right.get("object_path", ""),
                "object_2_version_id": right.get("version_id", ""),
                "object_2_schema": _fmt_object_schema(right),
                "object_2_blobs": right_total,
                "object_2_created_by": right.get("created_by", "unknown"),
                "object_2_created_at": right.get("created_at", "unknown"),
                "shared_blobs": shared,
                "blob_overlap_pct": _fmt_overlap_pct(shared, left_total, right_total),
                "compare_inputs": {
                    "left_instance_id": str(org_id),
                    "left_workspace_id": left.get("workspace_id", ""),
                    "left_object_id": left.get("object_id", ""),
                    "left_version": left.get("version_id", ""),
                    "right_instance_id": str(org_id),
                    "right_workspace_id": right.get("workspace_id", ""),
                    "right_object_id": right.get("object_id", ""),
                    "right_version": right.get("version_id", ""),
                },
            }
        )

    rows.sort(key=lambda row: (-_parse_pct(row["blob_overlap_pct"]), -row["shared_blobs"]))

    return {
        "summary": {
            "workspaces_scanned": len(workspace_stats),
            "total_objects_scanned": total_objects,
            "objects_with_blob_refs": objects_with_blobs,
            "objects_without_blob_refs": objects_without_blobs,
            "objects_with_fetch_errors": total_errors,
            "unique_blob_names": unique_blob_count,
            "duplicate_blob_names": duplicate_blob_count,
            "duplicate_object_pairs": len(rows),
        },
        "workspaces": workspace_stats,
        "duplicate_pairs": rows,
    }


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
    text = repr(value)
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


def _collect_crs_candidates(
    value: Any, *, path: str = "$", out: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
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


def _compare_json_payloads(
    left_payload: dict[str, Any], right_payload: dict[str, Any], *, max_differences: int
) -> dict[str, Any]:
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


async def _download_blob_response(
    download_url: str,
    connector: APIConnector,
    *,
    hub_url: str = "",
    session: aiohttp.ClientSession | None = None,
    request_headers: dict[str, str] | None = None,
    max_bytes: int = MAX_FULL_BLOB_DOWNLOAD_BYTES,
) -> tuple[bytes, dict[str, str], int]:
    """Download blob content, trying without auth first to avoid leaking tokens to pre-signed URLs."""
    timeout = aiohttp.ClientTimeout(total=300)
    base_headers = request_headers or {}

    def _normalized_origin(url: str) -> tuple[str, str, int] | None:
        parsed = urlparse(url)
        scheme = (parsed.scheme or "").lower()
        hostname = (parsed.hostname or "").lower()
        if not scheme or not hostname:
            return None
        try:
            port = parsed.port
        except ValueError:
            return None
        if port is None:
            port = 443 if scheme == "https" else 80 if scheme == "http" else None
            if port is None:
                return None
        return scheme, hostname, port

    async def _read_bounded(response: aiohttp.ClientResponse) -> bytes:
        """Read response body with a size cap to prevent OOM on oversized blobs."""
        content_length = response.content_length
        if content_length is not None and content_length > max_bytes:
            raise ValueError(
                f"Response Content-Length ({content_length:,} bytes) exceeds the "
                f"{max_bytes:,} byte download cap. Aborting before downloading."
            )
        buf = bytearray()
        async for chunk in response.content.iter_chunked(1024 * 1024):
            buf.extend(chunk)
            if len(buf) > max_bytes:
                raise ValueError(
                    f"Response body exceeded the {max_bytes:,} byte download cap "
                    f"after reading {len(buf):,} bytes. Download aborted."
                )
        return bytes(buf)

    async def _fetch(s: aiohttp.ClientSession) -> tuple[bytes, dict[str, str], int]:
        async with s.get(download_url, headers=base_headers) as response:
            if response.status not in {401, 403}:
                response.raise_for_status()
                return await _read_bounded(response), dict(response.headers), response.status

        if not hub_url:
            raise PermissionError(
                "Blob URL origin could not be validated because hub_url is missing; refusing to send auth headers."
            )

        download_origin = _normalized_origin(download_url)
        hub_origin = _normalized_origin(hub_url)
        if download_origin is None or hub_origin is None:
            raise PermissionError(
                f"Blob URL '{download_url}' or hub URL '{hub_url}' has an invalid or unsupported origin; "
                f"refusing to send auth headers."
            )

        download_scheme, download_host, download_port = download_origin
        hub_scheme, hub_host, hub_port = hub_origin

        if download_scheme != "https" or hub_scheme != "https":
            raise PermissionError(
                f"Authenticated blob retries require HTTPS origins; got blob origin "
                f"'{download_scheme}://{download_host}:{download_port}' and hub origin "
                f"'{hub_scheme}://{hub_host}:{hub_port}'."
            )

        if download_origin != hub_origin:
            raise PermissionError(
                f"Blob URL origin '{download_scheme}://{download_host}:{download_port}' does not match "
                f"hub origin '{hub_scheme}://{hub_host}:{hub_port}'; refusing to send auth headers "
                f"to a different origin."
            )

        auth_headers = await _get_authorization_headers(connector)
        if auth_headers:
            retry_headers = {**base_headers, **auth_headers}
            async with s.get(download_url, headers=retry_headers, allow_redirects=False) as retry_response:
                if 300 <= retry_response.status < 400:
                    location = retry_response.headers.get("Location", "<unknown>")
                    raise RuntimeError(
                        f"Authenticated blob request was redirected (HTTP {retry_response.status}) "
                        f"to '{location}'. Redirects are disabled on authenticated retries to "
                        f"prevent leaking auth headers to external hosts."
                    )
                retry_response.raise_for_status()
                return await _read_bounded(retry_response), dict(retry_response.headers), retry_response.status

        raise PermissionError("Unauthorized and no auth headers available")

    if session is not None:
        return await _fetch(session)

    async with aiohttp.ClientSession(timeout=timeout) as new_session:
        return await _fetch(new_session)


async def _download_blob_bytes(
    download_url: str,
    connector: APIConnector,
    *,
    hub_url: str = "",
    session: aiohttp.ClientSession | None = None,
) -> bytes:
    blob_bytes, _, _ = await _download_blob_response(
        download_url,
        connector,
        hub_url=hub_url,
        session=session,
    )
    return blob_bytes


def _content_range_total_size(headers: dict[str, str]) -> int | None:
    for key, value in headers.items():
        if key.lower() != "content-range":
            continue

        match = re.match(r"^bytes\s+\d+-\d+/(\d+)$", value)
        if match:
            return int(match.group(1))
    return None


def _parquet_footer_metadata_length(footer_bytes: bytes) -> int:
    if len(footer_bytes) < PARQUET_FOOTER_SIZE:
        raise ValueError("Parquet footer is truncated")
    if footer_bytes[-4:] != PARQUET_MAGIC:
        raise ValueError("Invalid Parquet footer magic")
    return int.from_bytes(footer_bytes[-8:-4], "little")


def _parquet_schema_fields(arrow_schema: pa.Schema) -> list[dict[str, Any]]:
    return [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
        }
        for field in arrow_schema
    ]


def _inspect_parquet_file(blob_name: str, parquet_file: pq.ParquetFile, *, size_bytes: int | None) -> dict[str, Any]:
    metadata = parquet_file.metadata
    format_version = getattr(metadata, "format_version", None)

    return {
        "blob_name": blob_name,
        "size_bytes": size_bytes,
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


def _inspect_parquet_footer_bytes(
    blob_name: str,
    footer_bytes: bytes,
    *,
    blob_size_bytes: int | None,
) -> dict[str, Any]:
    # Prepend PARQUET_MAGIC so PyArrow can parse the metadata-only buffer as a valid Parquet file.
    # Size is bounded by MAX_PARQUET_METADATA_BYTES + PARQUET_FOOTER_SIZE checked upstream.
    parquet_file = pq.ParquetFile(pa.BufferReader(PARQUET_MAGIC + footer_bytes))
    return _inspect_parquet_file(blob_name, parquet_file, size_bytes=blob_size_bytes)


async def _inspect_parquet_metadata(
    blob_name: str,
    download_url: str,
    connector: APIConnector,
    *,
    hub_url: str = "",
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
    footer_bytes, footer_headers, footer_status = await _download_blob_response(
        download_url,
        connector,
        hub_url=hub_url,
        session=session,
        request_headers={"Range": f"bytes=-{PARQUET_FOOTER_SIZE}"},
        max_bytes=PARQUET_FOOTER_SIZE,
    )

    if footer_status == 200:
        raise ValueError(
            f"Server does not support Range requests for blob '{blob_name}' "
            f"(returned HTTP 200 instead of 206). Cannot inspect Parquet metadata."
        )

    metadata_length = _parquet_footer_metadata_length(footer_bytes)
    if metadata_length > MAX_PARQUET_METADATA_BYTES:
        raise ValueError(
            f"Parquet metadata length ({metadata_length:,} bytes) exceeds safety cap "
            f"({MAX_PARQUET_METADATA_BYTES:,} bytes) for blob '{blob_name}'"
        )
    metadata_and_footer_size = metadata_length + PARQUET_FOOTER_SIZE
    tail_bytes, tail_headers, tail_status = await _download_blob_response(
        download_url,
        connector,
        hub_url=hub_url,
        session=session,
        request_headers={"Range": f"bytes=-{metadata_and_footer_size}"},
        max_bytes=metadata_and_footer_size,
    )

    if tail_status == 200:
        raise ValueError(
            f"Server does not support Range requests for blob '{blob_name}' "
            f"(returned HTTP 200 instead of 206). Cannot inspect Parquet metadata."
        )

    blob_size_bytes = _content_range_total_size(tail_headers) or _content_range_total_size(footer_headers)
    return _inspect_parquet_footer_bytes(blob_name, tail_bytes, blob_size_bytes=blob_size_bytes)


async def _inspect_data_link(
    link: dict[str, Any],
    connector: APIConnector,
    *,
    hub_url: str = "",
    session: aiohttp.ClientSession | None = None,
) -> dict[str, Any]:
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
        result.update(
            await _inspect_parquet_metadata(
                str(blob_name), str(download_url), connector, hub_url=hub_url, session=session
            )
        )
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
                "same_parquet_format_version": left_item.get("parquet_format_version")
                == right_item.get("parquet_format_version"),
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
                "same_parquet_format_version": left_item.get("parquet_format_version")
                == right_item.get("parquet_format_version"),
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


def _get_instance_hub_url(instance: Any) -> str:
    """Extract hub URL from an instance, raising a clear error if hubs are missing."""
    hubs = getattr(instance, "hubs", None)
    if not hubs:
        raise ValueError(f"Instance '{instance.display_name}' (id={instance.id}) has no hubs configured.")
    return hubs[0].url


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
                    "hub_url": _get_instance_hub_url(instance),
                }
        if current_org_id and evo_context.hub_url:
            return {
                "id": str(current_org_id),
                "name": "current_instance",
                "hub_url": evo_context.hub_url,
            }
        raise ValueError("No current Evo instance is selected.")

    for instance in instances:
        instance_id_str = str(instance.id).lower()
        if instance_id and instance_id.strip().lower() == instance_id_str:
            return {
                "id": str(instance.id),
                "name": instance.display_name,
                "hub_url": _get_instance_hub_url(instance),
            }
        if instance_name and instance.display_name == instance_name:
            return {
                "id": str(instance.id),
                "name": instance.display_name,
                "hub_url": _get_instance_hub_url(instance),
            }

    raise ValueError(f"Could not resolve instance for instance_id={instance_id!r}, instance_name={instance_name!r}.")


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
    object_payload = downloaded.as_dict()
    data_links = downloaded_object_data_links(downloaded)

    hub_url_for_auth = instance["hub_url"]
    timeout = aiohttp.ClientTimeout(total=300)
    inspect_semaphore = asyncio.Semaphore(PARQUET_INSPECTION_MAX_CONCURRENCY)

    async def _inspect_data_link_bounded(link: dict[str, Any]) -> dict[str, Any]:
        async with inspect_semaphore:
            return await _inspect_data_link(link, connector, hub_url=hub_url_for_auth, session=session)

    async with aiohttp.ClientSession(timeout=timeout) as session:
        parquet_files = await asyncio.gather(*[_inspect_data_link_bounded(link) for link in data_links])
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
            "created_at": metadata.created_at.isoformat() if metadata.created_at else None,
            "modified_at": metadata.modified_at.isoformat() if metadata.modified_at else None,
        },
        "json_payload": object_payload,
        "crs_candidates": _collect_crs_candidates(object_payload),
        "data_links": data_links,
        "parquet_files": parquet_files,
    }


def register_admin_tools(mcp):
    """Register all workspace-related tools with the FastMCP server."""

    @mcp.tool()
    async def create_workspace(name: str, description: str = "", labels: list[str] | None = None) -> dict:
        """Create a new workspace.

        Args:
            name: Workspace name
            description: Workspace description
            labels: Workspace labels (optional list)
        """
        await ensure_initialized()

        workspace = await evo_context.workspace_client.create_workspace(
            name=name, description=description, labels=labels or []
        )

        return {
            "id": str(workspace.id),
            "name": workspace.display_name,
            "description": workspace.description,
            "created_at": workspace.created_at.isoformat() if workspace.created_at else None,
        }

    @mcp.tool()
    async def get_workspace_summary(workspace_id: str) -> dict:
        """Get summary statistics for a workspace (object counts by type and file counts by extension).

        Args:
            workspace_id: Workspace UUID
        """
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        file_client = await evo_context.get_file_client(UUID(workspace_id))

        # Get all objects
        all_objects = await object_client.list_all_objects()

        # Count by schema type
        schema_counts = {}
        for obj in all_objects:
            schema = obj.schema_id.sub_classification
            schema_counts[schema] = schema_counts.get(schema, 0) + 1

        # Get all files
        all_files = await file_client.list_all_files()

        # Count files by extension
        extension_counts = {}
        for file in all_files:
            # Extract extension from filename
            name = file.name
            if "." in name:
                ext = name.rsplit(".", 1)[-1].lower()
            else:
                ext = "(no extension)"
            extension_counts[ext] = extension_counts.get(ext, 0) + 1

        return {
            "workspace_id": str(workspace_id),
            "total_objects": len(all_objects),
            "objects_by_schema": schema_counts,
            "total_files": len(all_files),
            "files_by_extension": extension_counts,
        }

    @mcp.tool()
    async def create_workspace_snapshot(
        workspace_id: str, snapshot_name: str = "", include_data_blobs: bool = False
    ) -> dict:
        """Create a snapshot of all objects and their current versions in a workspace.

        Args:
            workspace_id: Workspace UUID to snapshot
            snapshot_name: Optional name for the snapshot (defaults to timestamp)
            include_data_blobs: If True, include data blob references (increases size)

        Returns:
            Snapshot metadata and object version information
        """
        await ensure_initialized()
        object_client = await evo_context.get_object_client(UUID(workspace_id))
        workspace = await evo_context.workspace_client.get_workspace(UUID(workspace_id))

        # Get all objects
        all_objects = await object_client.list_all_objects()

        # Create snapshot
        timestamp = datetime.now(timezone.utc).isoformat()
        snapshot_name = snapshot_name or f"snapshot_{timestamp}"

        objects_snapshot = []

        for obj in all_objects:
            obj_info = {
                "id": str(obj.id),
                "name": obj.name,
                "path": obj.path,
                "schema_id": obj.schema_id.sub_classification,
                "version_id": obj.version_id,
                "created_at": obj.created_at.isoformat() if obj.created_at else None,
                # "updated_at": obj.updated_at.isoformat() if obj.updated_at else None
            }

            if include_data_blobs:
                try:
                    downloaded_obj = await object_client.download_object_by_id(obj.id, version=obj.version_id)
                    data_refs = extract_data_references(downloaded_obj.as_dict())
                    obj_info["data_blobs"] = data_refs
                except Exception:
                    obj_info["data_blobs"] = []

            objects_snapshot.append(obj_info)

        snapshot = {
            "snapshot_name": snapshot_name,
            "snapshot_timestamp": timestamp,
            "workspace_id": workspace_id,
            "workspace_name": workspace.display_name,
            "workspace_description": workspace.description,
            "object_count": len(objects_snapshot),
            "objects": objects_snapshot,
        }

        return {
            "snapshot": snapshot,
            "summary": {
                "snapshot_name": snapshot_name,
                "timestamp": timestamp,
                "workspace_id": workspace_id,
                "total_objects": len(objects_snapshot),
                "note_to_user": "Store this snapshot data to restore later using evo_restore_workspace_snapshot",
                "note_to_agent": "Display the full snapshot in your response.",
            },
        }

    @mcp.tool()
    async def workspace_copy_object(
        source_workspace_id: str, target_workspace_id: str, object_id: str, version: str = ""
    ) -> dict:
        """Copy a single object from one workspace to another, including data blobs.

        Args:
            source_workspace_id: Source workspace UUID
            target_workspace_id: Target workspace UUID
            object_id: Object UUID to copy
            version: Specific version ID (optional)
        """
        await ensure_initialized()
        source_client = await evo_context.get_object_client(UUID(source_workspace_id))
        target_client = await evo_context.get_object_client(UUID(target_workspace_id))

        # Download source object
        source_object = await source_client.download_object_by_id(UUID(object_id), version=version if version else None)

        # Extract and copy data blobs
        data_identifiers = extract_data_references(source_object.as_dict())
        if data_identifiers:
            await copy_object_data(source_client, target_client, source_object, data_identifiers, evo_context.connector)

        # Create object in target workspace
        object_dict = source_object.as_dict()
        object_dict["uuid"] = None

        new_metadata = await target_client.create_geoscience_object(source_object.metadata.path, object_dict)

        return {
            "id": str(new_metadata.id),
            "name": new_metadata.name,
            "path": new_metadata.path,
            "version_id": new_metadata.version_id,
            "data_blobs_copied": len(data_identifiers),
        }

    @mcp.tool()
    async def workspace_duplicate_workspace(
        source_workspace_id: str,
        target_name: str,
        target_description: str = "",
        schema_filter: list[str] = [],
        name_filter: list[str] = [],
    ) -> dict:
        """Duplicate entire workspace (all objects and data blobs).

        Args:
            source_workspace_id: Source workspace UUID
            target_name: Target workspace name
            target_description: Target workspace description
            schema_filter: Filter by object types (optional list)
            name_filter: Filter by object names (optional list)
        """
        await ensure_initialized()

        # Create target workspace
        target_workspace = await evo_context.workspace_client.create_workspace(
            name=target_name, description=target_description or "Duplicated workspace"
        )

        source_client = await evo_context.get_object_client(UUID(source_workspace_id))
        target_client = await evo_context.get_object_client(target_workspace.id)

        # Get all objects from source
        all_objects = await source_client.list_all_objects()

        # Apply filters
        filtered_objects = [
            obj
            for obj in all_objects
            if (not schema_filter or obj.schema_id.sub_classification in schema_filter)
            and (not name_filter or obj.name in name_filter)
        ]

        # Track progress
        copied_count = 0
        failed_count = 0
        cloned_data_ids = set()

        for obj in filtered_objects:
            try:
                # Download object
                source_object = await source_client.download_object_by_id(obj.id, version=obj.version_id)

                # Extract and copy new data blobs
                data_identifiers = extract_data_references(source_object.as_dict())
                new_data_identifiers = [d for d in data_identifiers if d not in cloned_data_ids]

                if new_data_identifiers:
                    await copy_object_data(
                        source_client, target_client, source_object, new_data_identifiers, evo_context.connector
                    )
                    cloned_data_ids.update(new_data_identifiers)

                # Create object in target
                object_dict = source_object.as_dict()
                object_dict["uuid"] = None

                await target_client.create_geoscience_object(source_object.metadata.path, object_dict)

                copied_count += 1

            except Exception:
                failed_count += 1
                # Continue with next object

        return {
            "target_workspace_id": str(target_workspace.id),
            "target_workspace_name": target_workspace.display_name,
            "objects_copied": copied_count,
            "objects_failed": failed_count,
            "data_blobs_copied": len(cloned_data_ids),
        }

    @mcp.tool()
    async def find_duplicate_objects(
        ctx: Context,
        workspace_ids: list[str] | None = None,
        workspace_names: list[str] | None = None,
        max_concurrent_fetches: int = 20,
        max_workspaces: int = 10,
        scan_all_workspaces: bool = False,
    ) -> dict:
        """Find duplicate objects across Evo workspaces by comparing blob hashes.

        Scans objects in the selected workspaces, fetches their data-blob references,
        and reports pairs of objects that share one or more blob hashes. This helps
        identify copied or redundant data.

        You can scope the analysis to specific workspaces or run it across the
        entire instance. Provide either workspace_ids or workspace_names (not both).

        When neither workspace_ids nor workspace_names is provided, the tool will
        scan up to `max_workspaces` workspaces. If the instance has more workspaces
        than the limit, the tool returns the full workspace list so you can select
        specific workspaces to scan. Set `scan_all_workspaces=True` to override
        this safety limit and scan every workspace (may be very slow).

        Use `preview_duplicate_scan` first to see workspace names and object counts
        before committing to a full scan.

        Args:
            workspace_ids: List of workspace UUIDs to scan (optional).
            workspace_names: List of workspace display names to scan (optional).
            max_concurrent_fetches: Max parallel object fetches (default 20).
            max_workspaces: Max workspaces to scan without explicit opt-in (default 10).
            scan_all_workspaces: Set True to scan all workspaces regardless of count.

        Returns:
            A dict with:
              - summary: high-level counts (workspaces scanned, objects, duplicates, etc.)
              - workspaces: per-workspace scan statistics
              - duplicate_pairs: list of object pairs with shared blobs, sorted by
                                overlap percentage descending. Each entry includes both objects'
                                workspace, object identifiers, schema, blob counts, overlap, and
                                a `compare_inputs` payload that can be passed directly to
                                `compare_evo_objects_detailed`.
        """
        if workspace_ids and workspace_names:
            return {"error": "Provide either workspace_ids or workspace_names, not both."}

        return await _run_duplicate_analysis(
            workspace_ids=workspace_ids,
            workspace_names=workspace_names,
            max_concurrent=max_concurrent_fetches,
            max_workspaces=max_workspaces,
            scan_all_workspaces=scan_all_workspaces,
            ctx=ctx,
        )

    @mcp.tool()
    async def preview_duplicate_scan() -> dict:
        """Preview workspaces and object counts before running a duplicate scan.

        Lists all workspaces in the current instance with the number of objects
        in each. Use this to decide which workspaces to include in a
        `find_duplicate_objects` call. No objects are downloaded.

        Returns:
            A dict with:
              - total_workspaces: number of workspaces in the instance
              - workspaces: list of {workspace_id, workspace_name, object_count}
                (object_count is -1 if listing failed for that workspace)
        """
        workspaces = await _preview_workspaces()
        return {
            "total_workspaces": len(workspaces),
            "workspaces": workspaces,
        }

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
        """
        if max_reported_differences < 1:
            return {"error": "max_reported_differences must be at least 1"}

        try:
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
        except asyncio.CancelledError:
            raise
        except (ValueError, PermissionError) as exc:
            return {"error": str(exc)}
        except Exception as exc:
            logger.exception("Unexpected failure while resolving objects for detailed comparison")
            return {"error": f"Unexpected error while resolving objects for comparison: {exc}"}

        left_crs_values = sorted(((entry["path"], entry["value"]) for entry in left_side["crs_candidates"]))
        right_crs_values = sorted(((entry["path"], entry["value"]) for entry in right_side["crs_candidates"]))
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
