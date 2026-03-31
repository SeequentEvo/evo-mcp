# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for designing estimation search neighborhoods."""

from __future__ import annotations

from typing import Any, Literal

from evo.compute.tasks.common import SearchNeighborhood
from evo.objects.typed import (
    Ellipsoid,
    EllipsoidRanges,
    Rotation,
    Variogram,
    object_from_uuid,
)

from evo_mcp.session import object_registry, ResolutionError
from evo_mcp.staging.errors import StageError
from evo_mcp.utils.tool_support import (
    VariogramObjectId,
    coerce_float,
    get_workspace_context,
    require_object_role,
)


def _resolve_scale_factor(
    preset: Literal["custom", "tight", "moderate", "broad"],
    scale_factor: float,
) -> float:
    if preset == "tight":
        return 1.0
    if preset == "moderate":
        return 2.0
    if preset == "broad":
        return 3.0
    return scale_factor

def _select_local_structure(
    structures: list[dict[str, Any]],
    structure_index: int | None,
    selection_mode: Literal["first", "largest_major"],
) -> tuple[int, dict[str, Any], str]:
    if len(structures) == 0:
        raise ValueError("No variogram structures available to select from.")

    if structure_index is not None:
        if structure_index < 0 or structure_index >= len(structures):
            raise ValueError(
                f"structure_index {structure_index} is out of range for {len(structures)} structure(s)."
            )
        return structure_index, structures[structure_index], "structure_index"

    if selection_mode == "largest_major":
        selected_index = max(
            range(len(structures)),
            key=lambda index: coerce_float(
                structures[index]
                .get("anisotropy", {})
                .get("ellipsoid_ranges", {})
                .get("major", 0.0),
                "anisotropy.ellipsoid_ranges.major",
            ),
        )
        return selected_index, structures[selected_index], "largest_major"

    return 0, structures[0], "first"


def register_search_neighborhood_tools(mcp) -> None:
    """Register search-neighborhood tools with the FastMCP server."""

    @mcp.tool()
    async def design_search_neighborhood(
        max_samples: int,
        workspace_id: str | None = None,
        min_samples: int | None = None,
        variogram_object_id: VariogramObjectId | None = None,
        variogram_name: str | None = None,
        major: float | None = None,
        semi_major: float | None = None,
        minor: float | None = None,
        structure_index: int | None = None,
        selection_mode: Literal["first", "largest_major"] = "first",
        scale_factor: float = 1.0,
        preset: Literal["custom", "tight", "moderate", "broad"] = "custom",
        dip_azimuth: float | None = None,
        dip: float | None = None,
        pitch: float | None = None,
    ) -> dict[str, Any]:
        """Design a canonical search neighborhood for local or workspace-backed estimation workflows.

        Local-only modes do not require workspace_id:
        - explicit major/semi_major/minor
        - registered variogram (variogram_name) + scale factor/preset

        Workspace-backed mode (variogram_object_id) requires workspace_id.
        """
        if max_samples < 1:
            raise ValueError("max_samples must be at least 1.")
        if min_samples is not None:
            if min_samples < 0:
                raise ValueError("min_samples must be non-negative.")
            if min_samples > max_samples:
                raise ValueError("min_samples cannot be greater than max_samples.")
        if scale_factor <= 0:
            raise ValueError("scale_factor must be greater than zero.")

        explicit_ranges = [major, semi_major, minor]
        has_explicit_ranges = any(value is not None for value in explicit_ranges)
        if has_explicit_ranges and not all(
            value is not None for value in explicit_ranges
        ):
            raise ValueError(
                "When specifying explicit neighborhood ranges, major, semi_major, and minor must all be provided."
            )

        if variogram_object_id is not None and variogram_name is not None:
            raise ValueError(
                "Provide either variogram_object_id or variogram_name, not both."
            )

        derivation_mode = "user-specified"
        derivation_details: dict[str, Any] = {
            "preset": preset,
            "scale_factor": scale_factor,
            "variogram_object_id": variogram_object_id,
        }

        if has_explicit_ranges:
            if any(v <= 0 for v in [major, semi_major, minor]):
                raise ValueError("Ellipsoid ranges must be positive values.")
            base_ranges = EllipsoidRanges(
                major=major,
                semi_major=semi_major,
                minor=minor,
            )
            base_rotation = Rotation(
                dip_azimuth=dip_azimuth or 0.0,
                dip=dip or 0.0,
                pitch=pitch or 0.0,
            )
        elif variogram_name is not None:
            try:
                _, variogram_data = object_registry.get_payload(
                    name=variogram_name, object_type="variogram"
                )
            except (StageError, ResolutionError) as exc:
                raise ValueError(str(exc)) from exc

            resolved_scale_factor = _resolve_scale_factor(preset, scale_factor)
            structures = variogram_data.get_structures_as_dicts()
            selected_index, selected_structure, selected_by = _select_local_structure(
                structures,
                structure_index,
                selection_mode,
            )

            ranges = selected_structure.get("anisotropy", {}).get(
                "ellipsoid_ranges", {}
            )
            major_value = coerce_float(
                ranges.get("major"), "anisotropy.ellipsoid_ranges.major"
            )
            semi_major_value = coerce_float(
                ranges.get("semi_major"),
                "anisotropy.ellipsoid_ranges.semi_major",
            )
            minor_value = coerce_float(
                ranges.get("minor"), "anisotropy.ellipsoid_ranges.minor"
            )
            if min(major_value, semi_major_value, minor_value) <= 0:
                raise ValueError(
                    "Staged variogram selected structure must have positive major, semi_major, and minor ranges."
                )

            rotation = selected_structure.get("anisotropy", {}).get("rotation", {})
            base_ranges = EllipsoidRanges(
                major=major_value * resolved_scale_factor,
                semi_major=semi_major_value * resolved_scale_factor,
                minor=minor_value * resolved_scale_factor,
            )
            base_rotation = Rotation(
                dip_azimuth=coerce_float(
                    rotation.get("dip_azimuth", 0.0), "anisotropy.rotation.dip_azimuth"
                ),
                dip=coerce_float(rotation.get("dip", 0.0), "anisotropy.rotation.dip"),
                pitch=coerce_float(
                    rotation.get("pitch", 0.0), "anisotropy.rotation.pitch"
                ),
            )
            scale_factor = resolved_scale_factor
            derivation_mode = "variogram-scaled"
            derivation_details.update(
                {
                    "variogram_object_id": None,
                    "variogram_name": variogram_name,
                    "selected_structure_index": selected_index,
                    "selected_by": selected_by,
                    "selection_mode": selection_mode,
                }
            )
        else:
            if variogram_object_id is None:
                raise ValueError(
                    "Provide either explicit ranges, a variogram_name, or a variogram_object_id to design the neighborhood."
                )
            if workspace_id is None:
                raise ValueError(
                    "workspace_id is required when variogram_object_id is provided."
                )

            context = await get_workspace_context(workspace_id)
            try:
                variogram_object = await object_from_uuid(context, variogram_object_id)
            except Exception as exc:
                raise ValueError(
                    "Could not resolve the variogram object for neighborhood design."
                ) from exc

            require_object_role(
                variogram_object,
                Variogram,
                "Variogram",
                "a Variogram",
            )

            resolved_scale_factor = _resolve_scale_factor(preset, scale_factor)

            base_ellipsoid = variogram_object.get_ellipsoid().scaled(
                resolved_scale_factor
            )
            base_ranges = base_ellipsoid.ranges
            base_rotation = base_ellipsoid.rotation
            scale_factor = resolved_scale_factor
            derivation_mode = "variogram-object-scaled"

        neighborhood_rotation = Rotation(
            dip_azimuth=(
                dip_azimuth if dip_azimuth is not None else base_rotation.dip_azimuth
            ),
            dip=dip if dip is not None else base_rotation.dip,
            pitch=pitch if pitch is not None else base_rotation.pitch,
        )

        neighborhood = SearchNeighborhood(
            ellipsoid=Ellipsoid(
                ranges=EllipsoidRanges(
                    major=base_ranges.major,
                    semi_major=base_ranges.semi_major,
                    minor=base_ranges.minor,
                ),
                rotation=neighborhood_rotation,
            ),
            max_samples=max_samples,
            min_samples=min_samples,
        )

        derivation_details["scale_factor"] = scale_factor

        return {
            "neighborhood": neighborhood.model_dump(mode="json", exclude_none=True),
            "derivation": {
                "mode": derivation_mode,
                **derivation_details,
            },
            "message": "Search neighborhood designed using canonical ellipsoid and sample-limit fields.",
        }
