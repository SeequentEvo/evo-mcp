# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for detecting duplicate objects across Evo workspaces.

Compares blob hashes referenced by objects to identify pairs that share
one or more data blobs, indicating potential duplicates.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from itertools import combinations
from typing import Any
from uuid import UUID

from evo.common.data import Environment
from evo.objects import ObjectAPIClient

from evo_mcp.context import evo_context, ensure_initialized

logger = logging.getLogger(__name__)


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
    from datetime import datetime, timezone

    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).strftime("%d/%m/%Y")
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
    org_id: UUID,
    workspace_id: UUID,
    workspace_name: str,
    object_metadata: Any,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    """Fetch full object details and extract blob references."""
    record: dict[str, Any] = {
        "workspace_id": str(workspace_id),
        "workspace_name": workspace_name,
        "object_id": str(object_metadata.id),
        "object_name": object_metadata.name,
        "object_path": object_metadata.path,
        "version_id": object_metadata.version_id,
        "schema_id": str(object_metadata.schema_id),
        "created_at": _fmt_dt(getattr(object_metadata, "created_at", None)),
        "created_by": _fmt_user(getattr(object_metadata, "created_by", None)),
        "updated_at": _fmt_dt(getattr(object_metadata, "modified_at", None)),
        "updated_by": _fmt_user(getattr(object_metadata, "modified_by", None)),
        "blob_hashes": [],
        "scan_error": None,
    }

    async with semaphore:
        try:
            response = await object_client._objects_api.get_object_by_id(
                object_id=str(object_metadata.id),
                org_id=str(org_id),
                workspace_id=str(workspace_id),
                version=object_metadata.version_id,
                additional_headers={"Accept-Encoding": "gzip"},
            )

            record["schema"] = response.object.model_dump(mode="python", by_alias=True).get("schema")

            for link in getattr(getattr(response, "links", None), "data", []) or []:
                blob_hash = str(getattr(link, "name", getattr(link, "id", "")))
                if blob_hash:
                    record["blob_hashes"].append(blob_hash)

            record["blob_hashes"].sort()
        except Exception as exc:
            record["scan_error"] = str(exc)

    return record


async def _run_duplicate_analysis(
    workspace_ids: list[str] | None,
    workspace_names: list[str] | None,
    max_concurrent: int,
) -> dict[str, Any]:
    """Core analysis logic shared by the MCP tool."""
    await ensure_initialized()

    # Resolve which workspaces to scan
    all_workspaces = await evo_context.workspace_client.list_workspaces(limit=500)
    ws_list = list(all_workspaces.items())

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

    org_id = evo_context.org_id
    hub_url = evo_context.hub_url
    semaphore = asyncio.Semaphore(max(1, max_concurrent))

    # Scan all objects across selected workspaces
    blob_index: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    object_lookup: dict[tuple[str, str], dict[str, Any]] = {}
    object_blob_counts: dict[tuple[str, str], int] = {}
    workspace_stats: list[dict[str, Any]] = []
    total_objects = 0
    total_errors = 0
    objects_with_blobs = 0
    objects_without_blobs = 0

    for workspace in ws_list:
        ws_name = workspace.display_name or str(workspace.id)
        ws_env = Environment(hub_url=hub_url, org_id=org_id, workspace_id=workspace.id)
        object_client = ObjectAPIClient(ws_env, evo_context.connector)

        try:
            objects = await object_client.list_all_objects(limit_per_request=5000)
        except Exception as exc:
            logger.warning("Failed to list objects in workspace %s: %s", ws_name, exc)
            workspace_stats.append({"name": ws_name, "id": str(workspace.id), "objects": 0, "error": str(exc)})
            continue

        scanned = await asyncio.gather(
            *[
                _scan_object(
                    object_client=object_client,
                    org_id=org_id,
                    workspace_id=workspace.id,
                    workspace_name=ws_name,
                    object_metadata=obj,
                    semaphore=semaphore,
                )
                for obj in objects
            ]
        )

        ws_object_count = len(scanned)
        ws_error_count = sum(1 for r in scanned if r["scan_error"])
        total_objects += ws_object_count
        total_errors += ws_error_count
        workspace_stats.append({"name": ws_name, "id": str(workspace.id), "objects": ws_object_count, "errors": ws_error_count})

        for rec in scanned:
            obj_key = (rec["workspace_id"], rec["object_id"])
            unique_blobs = set(rec["blob_hashes"])
            object_blob_counts[obj_key] = len(unique_blobs)

            if rec["scan_error"]:
                continue

            if unique_blobs:
                objects_with_blobs += 1
            else:
                objects_without_blobs += 1

            for blob_hash in unique_blobs:
                ref = {
                    "workspace_id": rec["workspace_id"],
                    "workspace_name": rec["workspace_name"],
                    "object_id": rec["object_id"],
                    "object_name": rec["object_name"],
                    "object_path": rec["object_path"],
                    "schema": rec.get("schema"),
                    "schema_id": rec["schema_id"],
                    "created_at": rec["created_at"],
                    "created_by": rec["created_by"],
                }
                blob_index[blob_hash].append(ref)
                object_lookup[obj_key] = ref

    # Build pair duplicate counts
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

    # Build result rows
    rows: list[dict[str, Any]] = []
    for (left_key, right_key), shared in sorted(
        pair_counts.items(), key=lambda item: (-item[1], item[0])
    ):
        left = object_lookup.get(left_key, {})
        right = object_lookup.get(right_key, {})
        left_total = object_blob_counts.get(left_key, 0)
        right_total = object_blob_counts.get(right_key, 0)
        rows.append({
            "object_1_workspace": left.get("workspace_name", "unknown"),
            "object_1_name": _clean_object_name(left),
            "object_1_schema": _fmt_object_schema(left),
            "object_1_blobs": left_total,
            "object_1_created_by": left.get("created_by", "unknown"),
            "object_1_created_at": left.get("created_at", "unknown"),
            "object_2_workspace": right.get("workspace_name", "unknown"),
            "object_2_name": _clean_object_name(right),
            "object_2_schema": _fmt_object_schema(right),
            "object_2_blobs": right_total,
            "object_2_created_by": right.get("created_by", "unknown"),
            "object_2_created_at": right.get("created_at", "unknown"),
            "shared_blobs": shared,
            "blob_overlap_pct": _fmt_overlap_pct(shared, left_total, right_total),
        })

    # Sort by overlap descending
    rows.sort(key=lambda r: (-_parse_pct(r["blob_overlap_pct"]), -r["shared_blobs"]))

    return {
        "summary": {
            "workspaces_scanned": len(workspace_stats),
            "total_objects_scanned": total_objects,
            "objects_with_blob_refs": objects_with_blobs,
            "objects_without_blob_refs": objects_without_blobs,
            "objects_with_fetch_errors": total_errors,
            "unique_blob_hashes": unique_blob_count,
            "duplicate_blob_hashes": duplicate_blob_count,
            "duplicate_object_pairs": len(rows),
        },
        "workspaces": workspace_stats,
        "duplicate_pairs": rows,
    }


def register_duplicate_tools(mcp):
    """Register duplicate-detection tools with the FastMCP server."""

    @mcp.tool()
    async def find_duplicate_objects(
        workspace_ids: list[str] | None = None,
        workspace_names: list[str] | None = None,
        max_concurrent_fetches: int = 20,
    ) -> dict:
        """Find duplicate objects across Evo workspaces by comparing blob hashes.

        Scans objects in the selected workspaces, fetches their data-blob references,
        and reports pairs of objects that share one or more blob hashes. This helps
        identify copied or redundant data.

        You can scope the analysis to specific workspaces or run it across the
        entire instance. Provide either workspace_ids or workspace_names (not both).
        If neither is provided, ALL workspaces in the current instance are scanned.

        Args:
            workspace_ids: List of workspace UUIDs to scan (optional).
            workspace_names: List of workspace display names to scan (optional).
            max_concurrent_fetches: Max parallel object fetches (default 20).

        Returns:
            A dict with:
              - summary: high-level counts (workspaces scanned, objects, duplicates, etc.)
              - workspaces: per-workspace scan statistics
              - duplicate_pairs: list of object pairs with shared blobs, sorted by
                overlap percentage descending. Each entry includes both objects'
                workspace, name, schema, blob counts, and the overlap percentage.
        """
        if workspace_ids and workspace_names:
            return {"error": "Provide either workspace_ids or workspace_names, not both."}

        return await _run_duplicate_analysis(
            workspace_ids=workspace_ids,
            workspace_names=workspace_names,
            max_concurrent=max_concurrent_fetches,
        )
