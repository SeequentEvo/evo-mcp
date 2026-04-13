# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Dev-only MCP tools for internal staging inspection and fixture management.

All tools in this module are gated behind MCP_DEV_MODE=true and are NOT
exposed in production. Staging is an internal implementation detail.

Tools:
  - stage_get_info, stage_clone, stage_discard, stage_list, stage_gc
  - seed, reset_staging
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from evo.objects.typed import (
    BlockModel,
    BlockModelData,
    EpsgCode,
    PointSet,
    PointSetData,
    Variogram,
)

from evo_mcp.context import ensure_initialized, evo_context
from evo_mcp.session import object_registry
from evo_mcp.staging.codecs import get_codec
from evo_mcp.staging.errors import StageError
from evo_mcp.staging.service import staging_service
from evo_mcp.utils.tool_support import get_workspace_context

logger = logging.getLogger(__name__)

_DEV_FIXTURE_TTL_SECONDS = 86_400
_VALID_SEED_MODES = ("staged", "workspace", "both")

# ── Private fixture helpers ───────────────────────────────────────────────────


def _stage_one(name: str, raw: dict, fixture_file: str) -> str:
    """Stage a single fixture locally and register it in the session registry.

    Returns the new stage_id.
    """
    raw = dict(raw)
    object_type = raw.pop("object_type")
    raw.pop("seed_mode", None)
    codec = get_codec(object_type)
    typed_payload = codec.from_dict(raw)
    envelope = staging_service.stage_local_build(
        object_type=object_type,
        typed_payload=typed_payload,
        source_ref={"fixture_name": name, "fixture_file": fixture_file},
        ttl_seconds=_DEV_FIXTURE_TTL_SECONDS,
    )
    object_registry.register(
        name=typed_payload.name,
        object_type=object_type,
        stage_id=envelope.stage_id,
        source="fixture",
        summary=envelope.summary,
    )
    logger.info("Staged '%s' → %s", name, envelope.stage_id)
    return envelope.stage_id


async def _publish_one(
    name: str,
    raw: dict,
    fixture_file: str,
    context: Any,
    workspace_id: str,
    also_stage: bool,
    path_prefix: str = "/fixtures",
) -> dict[str, Any]:
    """Publish a single fixture to a workspace, optionally also staging it locally.

    ``path_prefix`` lets callers namespace objects within a shared workspace
    (e.g. ``/fixtures/skill-name``) to avoid key collisions across files.

    Returns a published-object info dict.
    """
    raw = dict(raw)
    object_type = raw.pop("object_type")
    raw.pop("seed_mode", None)
    codec = get_codec(object_type)
    typed_payload = codec.from_dict(raw)

    if object_type == "variogram":
        object_path = f"{path_prefix}/variograms/{name}.json"
        published_obj = await Variogram.create(context, typed_payload, path=object_path)
    elif object_type == "point_set":
        object_path = f"{path_prefix}/pointsets/{name}.json"
        # The point set API requires EpsgCode objects, not plain "EPSG:NNNNN" strings.
        crs = typed_payload.coordinate_reference_system
        if isinstance(crs, str) and crs.upper().startswith("EPSG:"):
            try:
                typed_payload = PointSetData(
                    name=typed_payload.name,
                    description=typed_payload.description,
                    tags=typed_payload.tags,
                    coordinate_reference_system=EpsgCode(int(crs.split(":", 1)[1])),
                    locations=typed_payload.locations,
                )
            except (ValueError, IndexError):
                pass
        published_obj = await PointSet.create(context, typed_payload, path=object_path)
    elif object_type == "regular_block_model":
        object_path = f"{path_prefix}/blockmodels/{name}.json"
        published_obj = await BlockModel.create_regular(
            context, typed_payload, path=object_path
        )
    elif object_type == "block_model":
        raise ValueError(
            "Subblocked block models are import-only and cannot be published."
        )
    else:
        raise ValueError(f"Unknown object_type '{object_type}'.")

    metadata = published_obj.metadata
    obj_id = str(metadata.id)

    if also_stage:
        # For regular_block_model fixtures published with seed_mode="both", stage the
        # result as BlockModelData ("block_model" type) so the UUID is preserved and
        # mode=new_version can call BlockModel.replace() directly without an extra
        # API round-trip.
        if object_type == "regular_block_model":
            stage_payload = BlockModelData(
                name=typed_payload.name,
                description=typed_payload.description,
                coordinate_reference_system=typed_payload.coordinate_reference_system,
                block_model_uuid=published_obj.block_model_uuid,
                block_model_version_uuid=getattr(
                    published_obj, "block_model_version_uuid", None
                ),
                geometry=published_obj.geometry,
                attributes=list(published_obj.attributes),
            )
            stage_type = "block_model"
        else:
            stage_payload = typed_payload
            stage_type = object_type

        envelope = staging_service.stage_imported_object(
            object_type=stage_type,
            typed_payload=stage_payload,
            workspace_id=workspace_id,
            source_ref={
                "object_id": obj_id,
                "version_id": str(metadata.version_id) if metadata.version_id else None,
                "path": object_path,
            },
        )
        object_registry.register(
            name=stage_payload.name,
            object_type=stage_type,
            stage_id=envelope.stage_id,
            source="seeded",
            workspace_id=workspace_id,
            summary=envelope.summary,
        )

    logger.info("Published '%s' → %s (%s)", name, obj_id, object_type)
    return {
        "object_type": object_type,
        "object_name": typed_payload.name,
        "object_id": obj_id,
        "version_id": metadata.version_id,
        "path": object_path,
    }


# ── Tool registration ─────────────────────────────────────────────────────────


def register_dev_tools(mcp) -> None:
    """Register dev-only tools for staging inspection and fixture management."""

    @mcp.tool()
    async def stage_get_info(
        stage_id: str,
    ) -> dict[str, Any]:
        """Return the stage envelope for a given stage_id. Raises an error if stage not found or expired."""
        try:
            envelope = staging_service.get_stage_info(stage_id)
        except StageError as exc:
            raise ValueError(str(exc)) from exc
        return {"stage": envelope.to_dict()}

    @mcp.tool()
    async def stage_clone(
        stage_id: str,
    ) -> dict[str, Any]:
        """Clone an active stage into a new stage with source_type='cloned'. Returns the new stage envelope."""
        try:
            envelope = staging_service.clone_stage(stage_id)
        except StageError as exc:
            raise ValueError(str(exc)) from exc
        return {"stage": envelope.to_dict()}

    @mcp.tool()
    async def stage_discard(
        stage_id: str,
    ) -> dict[str, Any]:
        """Discard a stage by stage_id, releasing its stored payload."""
        try:
            staging_service.discard_stage(stage_id)
        except StageError as exc:
            raise ValueError(str(exc)) from exc
        return {"status": "discarded", "stage_id": stage_id}

    @mcp.tool()
    async def stage_list(
        object_type: str | None = None,
        workspace_id: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """List active or filtered stages. Optionally filter by object_type, workspace_id, or status."""
        envelopes = staging_service.list_stages(
            object_type=object_type,
            workspace_id=workspace_id,
            status=status,
            limit=limit,
        )
        return {
            "stages": [e.to_dict() for e in envelopes],
            "count": len(envelopes),
        }

    @mcp.tool()
    async def stage_gc(
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Garbage-collect expired and discarded stages. Set dry_run=False to actually remove them."""
        return staging_service.gc_stages(dry_run=dry_run)

    @mcp.tool()
    async def seed(
        fixture_files: list[str],
        fixture_names: list[str] | None = None,
    ) -> dict[str, Any]:
        """Seed fixtures from one or more fixture JSON files.

        Each fixture in the file must declare a ``seed_mode`` field:

        * ``"staged"``    — stage locally + register in session registry.
          No cloud calls. Fast, no auth required.
        * ``"workspace"`` — publish to a shared Evo workspace. Use for tools
          that need ``workspace_id`` and ``object_id`` values.
        * ``"both"``      — publish to workspace + stage locally as an imported
          object. Use when tools chain cloud-backed IDs with session-registry
          lookups.

        All fixtures that require a workspace share a single newly-created
        workspace. Workspace object paths are namespaced per file to prevent
        key collisions when seeding multiple fixture files at once.

        Args:
            fixture_files: One or more paths to ``fixtures.json`` files.
                Pass a single-element list for a per-skill run, or multiple
                paths to seed several skills in one call.
                Example: ``["skills/evo-kriging-run/evals/fixtures.json"]``
            fixture_names: Optional allow-list of fixture keys. When provided,
                only fixtures whose key appears in this list are seeded across
                all provided files.

        Returns:
            ``{workspace_id, workspace_name, results: {file_path: {staged,
            published, errors}}, totals: {staged, published, errors, files},
            message}``
        """
        if not fixture_files:
            raise ValueError("fixture_files must not be empty.")

        # Load all provided fixture files
        loaded: list[tuple[str, dict]] = []  # (file_path, fixtures_dict)
        load_errors: list[str] = []
        for fpath in fixture_files:
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    loaded.append((fpath, json.load(f)))
            except FileNotFoundError:
                load_errors.append(f"File not found: {fpath}")
            except Exception as exc:
                load_errors.append(f"Could not load '{fpath}': {exc}")

        if load_errors and not loaded:
            raise ValueError("\n".join(load_errors))

        # Determine whether a shared workspace is needed
        needs_workspace = any(
            fixture.get("seed_mode") in ("workspace", "both")
            for _, fixtures in loaded
            for fname, fixture in fixtures.items()
            if fixture_names is None or fname in fixture_names
        )

        workspace_id: str | None = None
        workspace_name: str | None = None
        context: Any = None

        if needs_workspace:
            await ensure_initialized()
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
            workspace_name = f"eval-{timestamp}"
            workspace = await evo_context.workspace_client.create_workspace(
                name=workspace_name,
                description="Eval workspace for fixture seeding",
                labels=[],
            )
            workspace_id = str(workspace.id)
            context = await get_workspace_context(workspace_id)
            logger.info("Created workspace '%s' (%s)", workspace_name, workspace_id)

        results: dict[str, Any] = {}
        total_staged = 0
        total_published = 0
        total_errors = 0

        for fixture_file, all_fixtures in loaded:
            names_to_seed = (
                [n for n in all_fixtures if n in fixture_names]
                if fixture_names is not None
                else list(all_fixtures.keys())
            )

            file_staged: dict[str, str] = {}
            file_published: dict[str, Any] = {}
            file_errors: dict[str, str] = {}

            # Derive a unique path namespace from the file's parent directory name
            path_prefix = f"/fixtures/{Path(fixture_file).parent.parent.name}"

            for name in names_to_seed:
                raw = all_fixtures.get(name)
                if raw is None:
                    file_errors[name] = (
                        f"'{name}' not found. Available: {list(all_fixtures.keys())}"
                    )
                    total_errors += 1
                    continue

                seed_mode = raw.get("seed_mode")
                if seed_mode is None:
                    file_errors[name] = f"Fixture '{name}' has no 'seed_mode' field."
                    total_errors += 1
                    logger.warning(
                        "Fixture '%s' in '%s' missing seed_mode.", name, fixture_file
                    )
                    continue

                if seed_mode not in _VALID_SEED_MODES:
                    file_errors[name] = (
                        f"Invalid seed_mode '{seed_mode}' on fixture '{name}'."
                    )
                    total_errors += 1
                    continue

                try:
                    if seed_mode == "staged":
                        file_staged[name] = _stage_one(name, raw, fixture_file)
                        total_staged += 1
                    else:
                        file_published[name] = await _publish_one(
                            name=name,
                            raw=raw,
                            fixture_file=fixture_file,
                            context=context,
                            workspace_id=workspace_id,
                            also_stage=(seed_mode == "both"),
                            path_prefix=path_prefix,
                        )
                        total_published += 1
                except Exception as exc:
                    file_errors[name] = str(exc)
                    total_errors += 1
                    logger.error(
                        "Failed to seed '%s' from '%s': %s", name, fixture_file, exc
                    )

            results[fixture_file] = {
                "staged": file_staged,
                "published": file_published,
                "errors": file_errors,
            }

        msg_parts = [
            f"Seeded {total_staged + total_published} fixture(s) from"
            f" {len(loaded)} file(s)."
        ]
        if total_staged:
            msg_parts.append(f"{total_staged} staged.")
        if total_published:
            msg_parts.append(
                f"{total_published} published to workspace"
                f" '{workspace_name}' ({workspace_id})."
            )
        if total_errors:
            msg_parts.append(f"{total_errors} error(s).")
        if load_errors:
            msg_parts.append(f"Failed to load: {load_errors}")

        return {
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "results": results,
            "totals": {
                "staged": total_staged,
                "published": total_published,
                "errors": total_errors,
                "files": len(loaded),
            },
            "message": " ".join(msg_parts),
        }

    @mcp.tool()
    async def reset_staging() -> dict[str, Any]:
        """Clear all staged objects and the session registry. Use before eval runs for a clean slate."""
        stages = staging_service.list_stages()
        discarded = 0
        for envelope in stages:
            try:
                staging_service.discard_stage(envelope.stage_id)
                discarded += 1
            except StageError:
                pass
        object_registry.clear()
        return {
            "status": "reset",
            "stages_discarded": discarded,
            "message": "All staged objects and registry entries cleared.",
        }
