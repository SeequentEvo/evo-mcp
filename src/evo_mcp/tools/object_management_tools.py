# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Object management tools — generic import and publish workflows.

Two tools cover all supported domain object types:
  - import_object  — fetches any Variogram, PointSet, or BlockModel from Evo
                     into the local session, auto-detecting the type.
  - publish_object — pushes a staged session object back to Evo, dispatching
                     on payload type (VariogramData / PointSetData /
                     RegularBlockModelData / BlockModelData).
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
    an ``EpsgCode`` object.
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
    """Register generic import/publish tools."""

    @mcp.tool()
    async def import_object(
        workspace_id: str,
        object_id: str,
        version_id: str | None = None,
    ) -> dict[str, Any]:
        """Import a published object from Evo into the session.

        Supports Variogram, PointSet, and BlockModel objects. The object type is
        detected automatically from the Evo schema.

        For block models, regular models can later be published back with
        publish_object(mode='new_version'). Non-regular (subblocked) models are
        imported as read-only references.
        """
        context = await get_workspace_context(workspace_id)
        try:
            obj = await object_from_uuid(context, object_id, version=version_id)
        except Exception as exc:
            raise ValueError(
                f"Could not resolve object '{object_id}' for import."
            ) from exc

        source_ref = {
            "object_id": str(obj.metadata.id),
            "version_id": str(obj.metadata.version_id)
            if obj.metadata.version_id
            else None,
            "path": getattr(obj.metadata, "path", None),
        }

        if isinstance(obj, Variogram):
            data = VariogramData(
                name=obj.name,
                description=getattr(obj, "description", None) or None,
                sill=obj.sill,
                is_rotation_fixed=obj.is_rotation_fixed,
                structures=obj.structures,
                nugget=obj.nugget,
                data_variance=obj.data_variance,
                modelling_space=obj.modelling_space,
                domain=obj.domain,
                attribute=obj.attribute,
            )
            object_type = "variogram"
            message = "Variogram imported."

        elif isinstance(obj, PointSet):
            dataframe = await obj.to_dataframe()
            data = PointSetData(
                name=obj.name,
                description=getattr(obj, "description", None),
                coordinate_reference_system=format_crs(extract_crs(obj)),
                locations=dataframe,
            )
            object_type = "point_set"
            message = "Point set imported."

        elif isinstance(obj, BlockModel):
            source_ref["schema_id"] = schema_label(obj)
            data = BlockModelData(
                name=obj.name,
                description=getattr(obj, "description", None),
                coordinate_reference_system=format_crs(extract_crs(obj)),
                block_model_uuid=obj.block_model_uuid,
                block_model_version_uuid=getattr(obj, "block_model_version_uuid", None),
                geometry=obj.geometry,
                attributes=list(obj.attributes),
            )
            object_type = "block_model"
            is_regular = getattr(obj.geometry, "model_type", None) == "regular"
            message = (
                "Regular block model imported. Can be published as a new version with publish_object(mode='new_version')."
                if is_regular
                else "Block model imported as reference (read-only; only regular block models can be published)."
            )

        else:
            raise ValueError(
                f"Object '{object_id}' has an unsupported type '{schema_label(obj)}'. "
                "Supported types: Variogram, PointSet, BlockModel."
            )

        envelope = staging_service.stage_imported_object(
            object_type=object_type,
            typed_payload=data,
            workspace_id=workspace_id,
            source_ref=source_ref,
        )
        object_registry.register(
            name=data.name,
            object_type=object_type,
            stage_id=envelope.stage_id,
            source="imported",
            workspace_id=workspace_id,
            summary=envelope.summary,
        )
        return {
            "name": data.name,
            "imported_from": source_ref,
            "message": message,
        }

    @mcp.tool()
    async def publish_object(
        workspace_id: str,
        object_name: str,
        mode: Literal["create", "new_version"],
        object_path: str | None = None,
        object_id: str | None = None,
    ) -> dict[str, Any]:
        """Publish a local session object to Evo.

        Supports Variogram, PointSet, and regular BlockModel objects. The object
        type is detected automatically from the staged payload.

        - mode='create': Creates a new Evo object. Requires object_path.
        - mode='new_version': Publishes as a new version of an existing object.
          Requires object_id. Only supported for imported objects (Variogram,
          PointSet, regular BlockModel).

        Note: Imported (subblocked) BlockModelData can only use mode='new_version'.
        Locally designed RegularBlockModelData can only use mode='create'.
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

        context = await get_workspace_context(workspace_id)
        staged_type = entry.object_type

        if isinstance(data, VariogramData):
            if mode == "create":
                try:
                    published = await Variogram.create(context, data, path=object_path)
                except Exception as exc:
                    raise ValueError(f"Failed to publish variogram as a new object: {exc}") from exc
            else:
                try:
                    existing = await object_from_uuid(context, object_id)
                except Exception as exc:
                    raise ValueError(
                        f"Could not resolve variogram '{object_id}' for new-version publish."
                    ) from exc
                require_object_role(existing, Variogram, "Variogram", "a Variogram")
                try:
                    published = await Variogram.replace(
                        context, str(existing.metadata.url), data
                    )
                except Exception as exc:
                    raise ValueError(f"Failed to publish variogram as a new version: {exc}") from exc

        elif isinstance(data, PointSetData):
            data = _coerce_point_set_crs(data)
            if mode == "create":
                try:
                    published = await PointSet.create(context, data, path=object_path)
                except Exception as exc:
                    raise ValueError(f"Failed to publish point set as a new object: {exc}") from exc
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
                        context, str(existing.metadata.url), data
                    )
                except Exception as exc:
                    raise ValueError(f"Failed to publish point set as a new version: {exc}") from exc

        elif isinstance(data, RegularBlockModelData):
            if mode != "create":
                raise ValueError(
                    f"'{object_name}' is a locally designed block model and can only be published with "
                    "mode='create'. To publish a new version, import the existing object first."
                )
            try:
                published = await BlockModel.create_regular(
                    context, data, path=object_path
                )
            except Exception as exc:
                raise ValueError(f"Failed to publish block model as a new object: {exc}") from exc

        elif isinstance(data, BlockModelData):
            if mode != "new_version":
                raise ValueError(
                    f"'{object_name}' is an imported block model and can only be published with "
                    "mode='new_version'. To create a new block model, design one locally first."
                )
            try:
                existing = await object_from_uuid(context, object_id)
            except Exception as exc:
                raise ValueError(
                    f"Could not resolve block model '{object_id}' for new-version publish."
                ) from exc
            require_object_role(existing, BlockModel, "Block model", "a BlockModel")
            # The staged BlockModelData already carries block_model_uuid — no extra
            # API round-trip needed to reconstruct it from the workspace object.
            try:
                published = await BlockModel.replace(
                    context, str(existing.metadata.url), data
                )
            except Exception as exc:
                raise ValueError(f"Failed to publish block model as a new version: {exc}") from exc

        else:
            raise ValueError(
                f"'{object_name}' has an unsupported payload type '{type(data).__name__}'. "
                "Supported types: VariogramData, PointSetData, RegularBlockModelData, BlockModelData."
            )

        staging_service.publish_stage(entry.stage_id)
        environment = await get_workspace_environment(workspace_id)
        metadata = published.metadata
        object_registry.mark_published(
            name=object_name,
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
