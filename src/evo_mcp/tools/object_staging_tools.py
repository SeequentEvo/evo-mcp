# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Object staging tools — a consistent interaction pattern for all staged objects.

All domain actions go through two generic tools:

  - staging_list_interactions  — list interactions available for an object type
  - staging_invoke_interaction — call an interaction on a staged object by name

Lifecycle tools that bring objects into/out of staging:

  - staging_list_object_types  — discover all stageable object types and their
                                 supported lifecycle operations
  - staging_import_object      — import an object from Evo into the session
  - staging_publish_object     — push a staged object back to Evo
  - staging_create_object      — create a new staged object locally
  - staging_discard_object     — remove a staged object from the session
  - staging_list               — list all staged objects in the session

Special staging tools:

  - staging_spatial_validation — validate spatial compatibility between staged objects

Object-type-specific logic (SDK calls, CRS coercion, etc.) lives in the
object type modules under ``evo_mcp.staging.objects``, not here.
"""

from typing import Any, Literal

from evo.objects.typed import object_from_uuid

from evo_mcp.session import ResolutionError, object_registry
from evo_mcp.staging.errors import StageError
from evo_mcp.staging.objects import staged_object_type_registry
from evo_mcp.staging.service import staging_service
from evo_mcp.utils.tool_support import (
    build_links_from_metadata,
    extract_crs,
    format_crs,
    get_workspace_context,
    get_workspace_environment,
    require_object_role,
    schema_label,
)


def _compare_crs(source_crs: Any, target_crs: Any) -> str:
    source_label = format_crs(source_crs)
    target_label = format_crs(target_crs)

    if source_label == "unspecified" or target_label == "unspecified":
        return "unknown"

    if source_label == target_label:
        return "compatible"

    return "mismatch"


def register_object_staging_tools(mcp) -> None:
    """Register generic staging interaction and lifecycle tools."""

    # ── Discovery ─────────────────────────────────────────────────────────────

    @mcp.tool()
    async def staging_list_object_types() -> dict[str, Any]:
        """List all object types that can be staged in this session.

        Returns each type with its supported lifecycle operations: ``create``
        (local build), ``import`` (from Evo), and ``publish`` modes back to Evo.

        Use ``staging_list_interactions`` with an ``object_type`` to see the
        interactions available once an object of that type is staged.
        """
        result = []
        for t in staged_object_type_registry.all():
            result.append(
                {
                    "object_type": t.object_type,
                    "display_name": t.display_name,
                    "supports_create": t.create_params_model is not None,
                    "supports_import": t.evo_class is not None,
                    "publish_modes": sorted(t.supported_publish_modes),
                }
            )
        return {"object_types": result}

    @mcp.tool()
    async def staging_list_interactions(object_type: str) -> dict[str, Any]:
        """List all interactions available for a staged object type.

        Returns each interaction name, description, and accepted parameters.
        Use ``staging_invoke_interaction`` to call any listed interaction on a
        staged object by name.

        Args:
            object_type: The object type identifier. Use ``staging_list_object_types``
                         to discover valid types.
        """
        staged_type = staged_object_type_registry.get_or_raise(object_type)
        return {
            "object_type": object_type,
            "display_name": staged_type.display_name,
            "interactions": staged_type.list_interactions(),
        }

    # ── Invoke ────────────────────────────────────────────────────────────────

    @mcp.tool()
    async def staging_invoke_interaction(
        object_name: str,
        interaction_name: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke a named interaction on a staged object.

        Use ``staging_list_interactions`` first to discover available interactions
        and their parameters for a given object type.

        Args:
            object_name: Name of the staged object in the session registry.
            interaction_name: Name of the interaction to invoke. Use ``staging_list_interactions``
                              to discover available names.
            params: Optional parameters for the interaction (depends on interaction).
        """
        try:
            entry, payload = object_registry.get_payload(name=object_name)
        except (StageError, ResolutionError) as exc:
            raise ValueError(str(exc)) from exc

        staged_type = staged_object_type_registry.get_or_raise(entry.object_type)
        result = await staged_type.invoke(interaction_name, payload, params)
        return {
            "object_name": entry.name,
            "object_type": entry.object_type,
            "interaction": interaction_name,
            "result": result,
        }

    # ── Lifecycle: create ─────────────────────────────────────────────────────

    @mcp.tool()
    async def staging_create_object(
        object_type: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new staged object of the given type locally.

        Use ``staging_list_object_types`` to see which types support local creation
        and the parameter schema required.
        """
        staged_type = staged_object_type_registry.get_or_raise(object_type)

        if staged_type.create_params_model is None:
            raise ValueError(
                f"Object type '{object_type}' does not support local creation. "
                f"Use staging_import_object instead."
            )

        try:
            validated_params = staged_type.create_params_model.model_validate(params)
        except Exception as exc:
            raise ValueError(
                f"Invalid parameters for '{object_type}' create: {exc}"
            ) from exc

        result = await staged_type.create(validated_params)
        return {
            "object_type": object_type,
            "result": result,
        }

    # ── Lifecycle: discard ────────────────────────────────────────────────────

    @mcp.tool()
    async def staging_discard_object(
        object_name: str,
    ) -> dict[str, Any]:
        """Remove a locally staged object from the session.

        Discards the staged payload and deregisters the object by name.
        This does not affect any published Evo objects.

        Args:
            object_name: Name of the staged object to remove.
        """
        try:
            entry = object_registry.resolve(name=object_name)
        except ResolutionError as exc:
            raise ValueError(str(exc)) from exc

        try:
            staging_service.discard_stage(entry.stage_id)
        except StageError as exc:
            raise ValueError(str(exc)) from exc

        object_registry.deregister(entry.name, entry.object_type)
        return {
            "object_name": entry.name,
            "object_type": entry.object_type,
            "status": "discarded",
            "message": f"'{entry.name}' has been removed from the session.",
        }

    # ── Lifecycle: list ───────────────────────────────────────────────────────

    @mcp.tool()
    async def staging_list(
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

    # ── Lifecycle: import ─────────────────────────────────────────────────────

    @mcp.tool()
    async def staging_import_object(
        workspace_id: str,
        object_id: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Import a published object from Evo into the session.

        The object type is detected automatically from the Evo schema.
        Use ``staging_list_object_types`` to see which types support import.
        """
        context = await get_workspace_context(workspace_id)
        try:
            obj = await object_from_uuid(context, object_id, version=version_id)
        except Exception as exc:
            raise ValueError(
                f"Could not resolve object '{object_id}' for import."
            ) from exc

        try:
            descriptor = staged_object_type_registry.get_by_evo_class(obj)
        except ValueError:
            raise ValueError(
                f"Object '{object_id}' has an unsupported type "
                f"'{schema_label(obj)}'. Supported types: "
                + ", ".join(d.display_name for d in staged_object_type_registry.all())
                + "."
            )

        source_ref: dict[str, Any] = {
            "object_id": str(obj.metadata.id),
            "version_id": str(obj.metadata.version_id)
            if obj.metadata.version_id
            else None,
            "path": getattr(obj.metadata, "path", None),
        }

        data, source_ref_extras, message = await descriptor.import_handler(obj, context)
        source_ref.update(source_ref_extras)

        envelope = staging_service.stage_imported_object(
            object_type=descriptor.object_type,
            typed_payload=data,
            workspace_id=workspace_id,
            source_ref=source_ref,
        )
        object_registry.register(
            name=data.name,
            object_type=descriptor.object_type,
            stage_id=envelope.stage_id,
            source="imported",
            workspace_id=workspace_id,
            summary=envelope.summary,
        )
        return {
            "name": data.name,
            "object_type": descriptor.object_type,
            "imported_from": source_ref,
            "message": message,
        }

    # ── Lifecycle: publish ────────────────────────────────────────────────────

    @mcp.tool()
    async def staging_publish_object(
        workspace_id: str,
        object_name: str,
        mode: Literal["create", "new_version"],
        object_path: str | None = None,
        object_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a staged object to Evo.

        The object type is detected automatically from the staged payload.
        Use ``staging_list_object_types`` to check which publish modes an object type supports.

        - mode='create': Creates a new Evo object. Requires object_path.
        - mode='new_version': Publishes as a new version of an existing object.
          Requires object_id.
        """
        if mode == "create" and not object_path:
            raise ValueError("object_path is required when mode='create'.")
        if mode == "new_version" and not object_id:
            raise ValueError("object_id is required when mode='new_version'.")

        try:
            entry = object_registry.resolve(name=object_name)
        except ResolutionError as exc:
            raise ValueError(str(exc)) from exc

        try:
            _, data = staging_service.get_stage_payload(entry.stage_id)
        except StageError as exc:
            raise ValueError(str(exc)) from exc

        descriptor = staged_object_type_registry.get_by_data_class(data)

        if mode not in descriptor.supported_publish_modes:
            raise ValueError(
                f"'{object_name}' ({descriptor.display_name}) does not support "
                f"mode='{mode}'. Supported modes: "
                f"{', '.join(sorted(descriptor.supported_publish_modes))}."
            )

        context = await get_workspace_context(workspace_id)

        if mode == "create":
            try:
                published = await descriptor.publish_create(context, data, object_path)
            except Exception as exc:
                raise ValueError(
                    f"Failed to publish {descriptor.display_name} as a new object: {exc}"
                ) from exc
        else:
            try:
                existing = await object_from_uuid(context, object_id)
            except Exception as exc:
                raise ValueError(
                    f"Could not resolve '{object_id}' for new-version publish."
                ) from exc
            require_object_role(
                existing,
                descriptor.evo_class,
                descriptor.role_label,
                descriptor.role_article,
            )
            try:
                published = await descriptor.publish_replace(
                    context, str(existing.metadata.url), data
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to publish {descriptor.display_name} as a new version: {exc}"
                ) from exc

        staging_service.publish_stage(entry.stage_id)
        environment = await get_workspace_environment(workspace_id)
        metadata = published.metadata
        object_registry.mark_published(
            name=object_name,
            object_type=entry.object_type,
            object_id=str(metadata.id),
            version_id=metadata.version_id,
            workspace_id=workspace_id,
        )
        return {
            "object_id": str(metadata.id),
            "version_id": metadata.version_id,
            "path": getattr(metadata, "path", None),
            "links": build_links_from_metadata(environment, str(metadata.id)),
        }

    # ── Spatial validation ────────────────────────────────────────────────────

    @mcp.tool()
    async def staging_spatial_validation(
        source_name: str,
        target_name: str,
    ) -> dict[str, Any]:
        """Validate spatial compatibility between two staged objects.

        Compares the coordinate reference systems of both objects using staged
        payloads only. No Evo API call required.

        Args:
            source_name: Name of the source staged object.
            target_name: Name of the target staged object.
        """
        try:
            source_entry, source_payload = object_registry.get_payload(
                name=source_name, object_type="point_set"
            )
        except (ResolutionError, Exception) as exc:
            raise ValueError(
                f"Could not resolve source '{source_name}' as a point set."
            ) from exc

        try:
            target_entry, target_payload = object_registry.get_payload(
                name=target_name, object_type="regular_block_model"
            )
        except (ResolutionError, Exception):
            try:
                target_entry, target_payload = object_registry.get_payload(
                    name=target_name, object_type="block_model"
                )
            except (ResolutionError, Exception) as exc:
                raise ValueError(
                    f"Could not resolve target '{target_name}' as a block model."
                ) from exc

        source_crs = extract_crs(source_payload)
        target_crs = extract_crs(target_payload)
        status = _compare_crs(source_crs, target_crs)

        if status == "compatible":
            message = "Source and target CRS match."
        elif status == "unknown":
            message = "At least one CRS is unspecified. Manual confirmation is required before execution."
        else:
            message = "Source and target CRS do not match. Resolve this before running kriging."

        return {
            "status": status,
            "message": message,
            "source": {
                "name": source_name,
                "object_type": source_entry.object_type,
                "coordinate_reference_system": format_crs(source_crs),
            },
            "target": {
                "name": target_name,
                "object_type": target_entry.object_type,
                "coordinate_reference_system": format_crs(target_crs),
            },
            "unit_context": {
                "guidance": (
                    "Search-neighborhood ranges should use the same coordinate units as the resolved CRS."
                )
            },
        }
