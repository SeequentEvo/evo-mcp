# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Object management tools — import and publish workflows.

Centralised import/publish tools for all domain object types
(variogram, point_set, block_model).
"""

from typing import Any, Literal

from evo.blockmodels.typed import RegularBlockModelData
from evo.objects.typed import (
    BlockModel,
    BlockModelData,
    EpsgCode,
    PointSet,
    PointSetData,
    Variogram,
    VariogramData,
    object_from_uuid,
)

from evo_mcp.session import object_registry, ResolutionError
from evo_mcp.staging.errors import StageError
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


def _coerce_point_set_crs(point_set_data: PointSetData) -> PointSetData:
    """Return a copy of *point_set_data* with its CRS converted to EpsgCode.

    The PointSet publish API rejects plain ``"EPSG:NNNNN"`` strings; it requires
    an ``EpsgCode`` object.  This mirrors the same conversion in dev_tools.py.
    """
    crs = point_set_data.coordinate_reference_system
    if isinstance(crs, str) and crs.upper().startswith("EPSG:"):
        try:
            return PointSetData(
                name=point_set_data.name,
                description=point_set_data.description,
                tags=point_set_data.tags,
                coordinate_reference_system=EpsgCode(int(crs.split(":", 1)[1])),
                locations=point_set_data.locations,
            )
        except (ValueError, IndexError):
            pass
    return point_set_data


def register_object_management_tools(mcp) -> None:
    """Register import/publish tools for all domain object types."""

    # -- Variogram import/publish ------------------------------------------

    @mcp.tool()
    async def variogram_import(
        workspace_id: str,
        variogram_object_id: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Import a published variogram from Evo into the session."""
        context = await get_workspace_context(workspace_id)
        try:
            variogram = await object_from_uuid(
                context,
                variogram_object_id,
                version=version_id,
            )
        except Exception as exc:
            raise ValueError(
                f"Could not resolve variogram '{variogram_object_id}' for import."
            ) from exc

        require_object_role(variogram, Variogram, "Variogram", "a Variogram")

        variogram_data = VariogramData(
            name=variogram.name,
            description=getattr(variogram, "description", None) or None,
            sill=variogram.sill,
            is_rotation_fixed=variogram.is_rotation_fixed,
            structures=variogram.structures,
            nugget=variogram.nugget,
            data_variance=variogram.data_variance,
            modelling_space=variogram.modelling_space,
            domain=variogram.domain,
            attribute=variogram.attribute,
        )

        source_ref = {
            "object_id": str(variogram.metadata.id),
            "version_id": str(variogram.metadata.version_id)
            if variogram.metadata.version_id
            else None,
            "path": getattr(variogram.metadata, "path", None),
        }
        envelope = staging_service.stage_imported_object(
            object_type="variogram",
            typed_payload=variogram_data,
            workspace_id=workspace_id,
            source_ref=source_ref,
        )

        object_registry.register(
            name=variogram_data.name,
            object_type="variogram",
            stage_id=envelope.stage_id,
            source="imported",
            workspace_id=workspace_id,
            summary=envelope.summary,
        )
        return {
            "name": variogram_data.name,
            "imported_from": source_ref,
            "message": "Variogram imported.",
        }

    @mcp.tool()
    async def variogram_publish(
        workspace_id: str,
        variogram_name: str,
        mode: Literal["create", "new_version"],
        object_path: str | None = None,
        object_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a variogram to Evo by name."""
        if mode == "create":
            if not object_path:
                raise ValueError("object_path is required when mode='create'.")
        else:
            if not object_id:
                raise ValueError("object_id is required when mode='new_version'.")

        try:
            entry = object_registry.resolve(
                name=variogram_name, object_type="variogram"
            )
        except ResolutionError as exc:
            raise ValueError(str(exc)) from exc

        try:
            _, variogram_data = staging_service.get_stage_payload(entry.stage_id)
        except StageError as exc:
            raise ValueError(str(exc)) from exc

        if not isinstance(variogram_data, VariogramData):
            raise ValueError(
                f"Variogram '{variogram_name}' does not contain a VariogramData payload."
            )

        context = await get_workspace_context(workspace_id)

        if mode == "create":
            try:
                published_variogram = await Variogram.create(
                    context,
                    variogram_data,
                    path=object_path,
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to publish variogram as a new object: {exc}"
                ) from exc
        else:
            try:
                existing_variogram = await object_from_uuid(context, object_id)
            except Exception as exc:
                raise ValueError(
                    f"Could not resolve variogram '{object_id}' for new-version publish."
                ) from exc
            require_object_role(
                existing_variogram,
                Variogram,
                "Variogram",
                "a Variogram",
            )
            try:
                published_variogram = await Variogram.replace(
                    context,
                    str(existing_variogram.metadata.url),
                    variogram_data,
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to publish variogram as a new version: {exc}"
                ) from exc

        staging_service.publish_stage(entry.stage_id)
        environment = await get_workspace_environment(workspace_id)
        metadata = published_variogram.metadata
        object_registry.mark_published(
            name=variogram_name,
            object_type="variogram",
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

    # -- PointSet import/publish -------------------------------------------

    @mcp.tool()
    async def point_set_import(
        workspace_id: str,
        point_set_object_id: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Import a published PointSet from Evo into the session."""
        context = await get_workspace_context(workspace_id)
        try:
            point_set_object = await object_from_uuid(
                context,
                point_set_object_id,
                version=version_id,
            )
        except Exception as exc:
            raise ValueError(
                f"Could not resolve point set '{point_set_object_id}' for import."
            ) from exc

        require_object_role(point_set_object, PointSet, "PointSet", "a PointSet")

        dataframe = await point_set_object.to_dataframe()
        point_set_data = PointSetData(
            name=point_set_object.name,
            description=getattr(point_set_object, "description", None),
            coordinate_reference_system=format_crs(extract_crs(point_set_object)),
            locations=dataframe,
        )
        metadata = point_set_object.metadata
        source_ref = {
            "object_id": str(metadata.id),
            "version_id": str(metadata.version_id) if metadata.version_id else None,
            "path": getattr(metadata, "path", None),
        }
        envelope = staging_service.stage_imported_object(
            object_type="point_set",
            typed_payload=point_set_data,
            workspace_id=workspace_id,
            source_ref=source_ref,
        )
        object_registry.register(
            name=point_set_data.name,
            object_type="point_set",
            stage_id=envelope.stage_id,
            source="imported",
            workspace_id=workspace_id,
            summary=envelope.summary,
        )
        return {
            "name": point_set_data.name,
            "imported_from": source_ref,
            "message": "Point set imported.",
        }

    @mcp.tool()
    async def point_set_publish(
        workspace_id: str,
        point_set_name: str,
        mode: Literal["create", "new_version"],
        object_path: str | None = None,
        object_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a point set to Evo by name."""
        if mode == "create":
            if not object_path:
                raise ValueError("object_path is required when mode='create'.")
        else:
            if not object_id:
                raise ValueError("object_id is required when mode='new_version'.")

        try:
            entry = object_registry.resolve(
                name=point_set_name, object_type="point_set"
            )
        except ResolutionError as exc:
            raise ValueError(str(exc)) from exc

        try:
            _, point_set_data = staging_service.get_stage_payload(entry.stage_id)
        except StageError as exc:
            raise ValueError(str(exc)) from exc

        if not isinstance(point_set_data, PointSetData):
            raise ValueError(
                f"Point set '{point_set_name}' does not contain a PointSetData payload."
            )

        context = await get_workspace_context(workspace_id)
        point_set_data = _coerce_point_set_crs(point_set_data)

        if mode == "create":
            try:
                published = await PointSet.create(
                    context,
                    point_set_data,
                    path=object_path,
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to publish point set as a new object: {exc}"
                ) from exc
        else:
            try:
                existing = await object_from_uuid(context, object_id)
            except Exception as exc:
                raise ValueError(
                    f"Could not resolve point set '{object_id}' for new-version publish."
                ) from exc

            require_object_role(existing, PointSet, "PointSet", "a PointSet")
            try:
                published = await PointSet.replace(
                    context,
                    str(existing.metadata.url),
                    point_set_data,
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to publish point set as a new version: {exc}"
                ) from exc

        staging_service.publish_stage(entry.stage_id)
        environment = await get_workspace_environment(workspace_id)
        metadata = published.metadata
        object_registry.mark_published(
            name=point_set_name,
            object_type="point_set",
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

    # -- BlockModel import/publish -----------------------------------------

    @mcp.tool()
    async def block_model_import(
        workspace_id: str,
        block_model_object_id: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Import a published BlockModel from Evo into the session."""
        context = await get_workspace_context(workspace_id)
        try:
            block_model = await object_from_uuid(
                context,
                block_model_object_id,
                version=version_id,
            )
        except Exception as exc:
            raise ValueError(
                f"Could not resolve block model '{block_model_object_id}' for import."
            ) from exc

        require_object_role(block_model, BlockModel, "Block model", "a BlockModel")

        block_model_data = BlockModelData(
            name=block_model.name,
            description=getattr(block_model, "description", None),
            coordinate_reference_system=format_crs(extract_crs(block_model)),
            block_model_uuid=block_model.block_model_uuid,
            block_model_version_uuid=getattr(
                block_model, "block_model_version_uuid", None
            ),
            geometry=block_model.geometry,
            attributes=list(block_model.attributes),
        )
        source_ref = {
            "object_id": str(block_model.metadata.id),
            "version_id": str(block_model.metadata.version_id)
            if block_model.metadata.version_id
            else None,
            "path": getattr(block_model.metadata, "path", None),
            "schema_id": schema_label(block_model),
        }
        envelope = staging_service.stage_imported_object(
            object_type="block_model",
            typed_payload=block_model_data,
            workspace_id=workspace_id,
            source_ref=source_ref,
        )
        object_registry.register(
            name=block_model_data.name,
            object_type="block_model",
            stage_id=envelope.stage_id,
            source="imported",
            workspace_id=workspace_id,
            summary=envelope.summary,
        )
        return {
            "name": block_model_data.name,
            "imported_from": source_ref,
            "message": "Block model imported as reference (read-only).",
        }

    @mcp.tool()
    async def regular_block_model_import(
        workspace_id: str,
        block_model_object_id: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Import a published regular BlockModel from Evo into the session.

        Only accepts regular block models (model_type='regular'). The imported object
        is staged as BlockModelData (preserving block_model_uuid) and can be published
        as a new version using regular_block_model_publish with mode='new_version'.
        """
        context = await get_workspace_context(workspace_id)
        try:
            block_model = await object_from_uuid(
                context,
                block_model_object_id,
                version=version_id,
            )
        except Exception as exc:
            raise ValueError(
                f"Could not resolve block model '{block_model_object_id}' for import."
            ) from exc

        require_object_role(block_model, BlockModel, "Block model", "a BlockModel")

        geometry = block_model.geometry
        if geometry.model_type != "regular":
            raise ValueError(
                f"Block model '{block_model_object_id}' is not a regular block model "
                f"(model_type={geometry.model_type!r}). Use block_model_import for non-regular models."
            )

        # Store as BlockModelData (preserves block_model_uuid) so mode=new_version
        # can call BlockModel.replace() directly without an extra API round-trip.
        block_model_data = BlockModelData(
            name=block_model.name,
            description=getattr(block_model, "description", None),
            coordinate_reference_system=format_crs(extract_crs(block_model)),
            block_model_uuid=block_model.block_model_uuid,
            block_model_version_uuid=getattr(
                block_model, "block_model_version_uuid", None
            ),
            geometry=block_model.geometry,
            attributes=list(block_model.attributes),
        )
        source_ref = {
            "object_id": str(block_model.metadata.id),
            "version_id": str(block_model.metadata.version_id)
            if block_model.metadata.version_id
            else None,
            "path": getattr(block_model.metadata, "path", None),
            "schema_id": schema_label(block_model),
        }
        envelope = staging_service.stage_imported_object(
            object_type="block_model",
            typed_payload=block_model_data,
            workspace_id=workspace_id,
            source_ref=source_ref,
        )
        object_registry.register(
            name=block_model_data.name,
            object_type="block_model",
            stage_id=envelope.stage_id,
            source="imported",
            workspace_id=workspace_id,
            summary=envelope.summary,
        )
        return {
            "name": block_model_data.name,
            "imported_from": source_ref,
            "message": "Regular block model imported (staged as block_model reference with UUID).",
        }

    @mcp.tool()
    async def regular_block_model_publish(
        workspace_id: str,
        block_model_name: str,
        mode: Literal["create", "new_version"],
        object_path: str | None = None,
        object_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a regular block model to Evo by name. Only regular block models can be published."""
        if mode == "create":
            if not object_path:
                raise ValueError("object_path is required when mode='create'.")
        else:
            if not object_id:
                raise ValueError("object_id is required when mode='new_version'.")

        # mode=create: locally designed model (RegularBlockModelData, no UUID)
        # mode=new_version: imported model (BlockModelData, has block_model_uuid)
        staged_type = "regular_block_model" if mode == "create" else "block_model"
        try:
            entry = object_registry.resolve(
                name=block_model_name, object_type=staged_type
            )
        except ResolutionError as exc:
            raise ValueError(str(exc)) from exc

        try:
            _, block_model_data = staging_service.get_stage_payload(entry.stage_id)
        except StageError as exc:
            raise ValueError(str(exc)) from exc

        context = await get_workspace_context(workspace_id)

        if mode == "create":
            if not isinstance(block_model_data, RegularBlockModelData):
                raise ValueError(
                    f"Block model '{block_model_name}' does not contain a RegularBlockModelData payload."
                )
            try:
                published_block_model = await BlockModel.create_regular(
                    context,
                    block_model_data,
                    path=object_path,
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to publish block model as a new object: {exc}"
                ) from exc
        else:
            if not isinstance(block_model_data, BlockModelData):
                raise ValueError(
                    f"Block model '{block_model_name}' was not imported as a block_model reference. "
                    "Use regular_block_model_import to import the block model first, then publish "
                    "with mode='new_version'."
                )
            try:
                existing_block_model = await object_from_uuid(context, object_id)
            except Exception as exc:
                raise ValueError(
                    f"Could not resolve block model '{object_id}' for new-version publish."
                ) from exc

            require_object_role(
                existing_block_model,
                BlockModel,
                "Block model",
                "a BlockModel",
            )
            # The staged BlockModelData already carries the block_model_uuid — call
            # BlockModel.replace() directly without reconstructing from the workspace object.
            try:
                published_block_model = await BlockModel.replace(
                    context,
                    str(existing_block_model.metadata.url),
                    block_model_data,
                )
            except Exception as exc:
                raise ValueError(
                    f"Failed to publish block model as a new version: {exc}"
                ) from exc

        staging_service.publish_stage(entry.stage_id)
        environment = await get_workspace_environment(workspace_id)
        metadata = published_block_model.metadata
        object_registry.mark_published(
            name=block_model_name,
            object_type=staged_type,
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
