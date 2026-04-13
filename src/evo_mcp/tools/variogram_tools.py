# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for local variogram workflows.

Tools for creating and inspecting variogram data. Objects are tracked by name
via the session registry.
"""

import math
from typing import Any, Literal

import numpy as np
from evo.objects.typed import (
    CubicStructure,
    Ellipsoid,
    EllipsoidRanges,
    ExponentialStructure,
    GaussianStructure,
    GeneralisedCauchyStructure,
    LinearStructure,
    Rotation,
    SphericalStructure,
    SpheroidalStructure,
    VariogramData,
)

# NOTE: _evaluate_structure is a private SDK API; may change across evo-python-sdk versions.
# If this breaks, implement local structure evaluation or request SDK to expose it publicly.
from evo.objects.typed.variogram import _evaluate_structure

from evo_mcp.session import object_registry, ResolutionError
from evo_mcp.staging.errors import StageError
from evo_mcp.staging.service import staging_service
from evo.compute.tasks import (
    Ellipsoid as ComputeEllipsoid,
    EllipsoidRanges as ComputeEllipsoidRanges,
    Rotation as ComputeRotation,
)


def _variogram_structure_from_inputs(
    structure_type: str,
    contribution: float,
    ellipsoid: Ellipsoid,
    alpha: int | None = None,
) -> Any:
    structure_type_lower = structure_type.lower()
    if structure_type_lower == "spherical":
        return SphericalStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "exponential":
        return ExponentialStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "gaussian":
        return GaussianStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "cubic":
        return CubicStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "linear":
        return LinearStructure(contribution=contribution, anisotropy=ellipsoid)
    if structure_type_lower == "spheroidal":
        return SpheroidalStructure(
            contribution=contribution,
            anisotropy=ellipsoid,
            alpha=alpha,
        )
    if structure_type_lower == "generalisedcauchy":
        return GeneralisedCauchyStructure(
            contribution=contribution,
            anisotropy=ellipsoid,
            alpha=alpha,
        )
    raise ValueError(
        "Unsupported structure_type. Use spherical, exponential, gaussian, cubic, linear, spheroidal, or generalisedcauchy."
    )


def _validate_variogram_structure_alpha(
    structure_type: str,
    alpha: int | None,
) -> None:
    structure_type_lower = structure_type.lower()
    alpha_required_types = {"spheroidal", "generalisedcauchy"}
    valid_alpha_values = {3, 5, 7, 9}

    if structure_type_lower in alpha_required_types:
        if alpha is None:
            raise ValueError(
                f"alpha is required for {structure_type_lower} variogram structures."
            )
        if alpha not in valid_alpha_values:
            raise ValueError(
                f"alpha must be one of {sorted(valid_alpha_values)} for {structure_type_lower} variogram structures."
            )
        return

    if alpha is not None:
        raise ValueError(
            f"alpha is only valid for spheroidal or generalisedcauchy variogram structures, not {structure_type_lower}."
        )


def _coerce_structure_float(value: Any, field_name: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be numeric; got {value!r}.") from exc


def _build_structure_from_payload(
    structure_payload: dict[str, Any],
    structure_index: int,
) -> Any:
    if not isinstance(structure_payload, dict):
        raise ValueError(
            f"structures[{structure_index}] must be an object; got {type(structure_payload).__name__}."
        )

    structure_type = structure_payload.get("variogram_type")
    if not structure_type:
        raise ValueError(f"structures[{structure_index}].variogram_type is required.")

    contribution = _coerce_structure_float(
        structure_payload.get("contribution"),
        f"structures[{structure_index}].contribution",
    )
    if contribution <= 0:
        raise ValueError(
            f"structures[{structure_index}].contribution must be greater than zero."
        )

    anisotropy = structure_payload.get("anisotropy")
    if not isinstance(anisotropy, dict):
        raise ValueError(
            f"structures[{structure_index}].anisotropy is required and must be an object."
        )

    ranges = anisotropy.get("ellipsoid_ranges")
    if not isinstance(ranges, dict):
        raise ValueError(
            f"structures[{structure_index}].anisotropy.ellipsoid_ranges is required and must be an object."
        )

    major = _coerce_structure_float(
        ranges.get("major"),
        f"structures[{structure_index}].anisotropy.ellipsoid_ranges.major",
    )
    semi_major = _coerce_structure_float(
        ranges.get("semi_major"),
        f"structures[{structure_index}].anisotropy.ellipsoid_ranges.semi_major",
    )
    minor = _coerce_structure_float(
        ranges.get("minor"),
        f"structures[{structure_index}].anisotropy.ellipsoid_ranges.minor",
    )
    if min(major, semi_major, minor) <= 0:
        raise ValueError(
            f"structures[{structure_index}] major, semi_major, and minor must all be greater than zero."
        )

    rotation_payload = anisotropy.get("rotation") or {}
    if not isinstance(rotation_payload, dict):
        raise ValueError(
            f"structures[{structure_index}].anisotropy rotation must be an object when provided."
        )

    dip_azimuth = _coerce_structure_float(
        rotation_payload.get("dip_azimuth", 0.0),
        f"structures[{structure_index}].anisotropy.rotation.dip_azimuth",
    )
    dip = _coerce_structure_float(
        rotation_payload.get("dip", 0.0),
        f"structures[{structure_index}].anisotropy.rotation.dip",
    )
    pitch = _coerce_structure_float(
        rotation_payload.get("pitch", 0.0),
        f"structures[{structure_index}].anisotropy.rotation.pitch",
    )

    alpha = structure_payload.get("alpha")
    _validate_variogram_structure_alpha(str(structure_type), alpha)

    ellipsoid = Ellipsoid(
        ranges=EllipsoidRanges(
            major=major,
            semi_major=semi_major,
            minor=minor,
        ),
        rotation=Rotation(
            dip_azimuth=dip_azimuth,
            dip=dip,
            pitch=pitch,
        ),
    )
    return _variogram_structure_from_inputs(
        str(structure_type),
        contribution,
        ellipsoid,
        alpha,
    )


def _build_variogram_structures(structures_payload: list[dict[str, Any]]) -> list[Any]:
    if len(structures_payload) == 0:
        raise ValueError("structures must contain at least one structure.")

    return [
        _build_structure_from_payload(structure_payload, structure_index)
        for structure_index, structure_payload in enumerate(structures_payload)
    ]


def _select_structure_from_payload(
    structures: list[dict[str, Any]],
    structure_index: int | None,
    selection_mode: Literal["first", "largest_major"],
) -> tuple[int, dict[str, Any], str]:
    if not structures:
        raise ValueError("variogram_data must contain at least one structure.")

    if structure_index is not None:
        if structure_index < 0 or structure_index >= len(structures):
            raise ValueError(
                f"structure_index {structure_index} is out of range for {len(structures)} structure(s)."
            )
        return structure_index, structures[structure_index], "structure_index"

    if selection_mode == "largest_major":
        selected_index = max(
            range(len(structures)),
            key=lambda index: _coerce_structure_float(
                structures[index]
                .get("anisotropy", {})
                .get("ellipsoid_ranges", {})
                .get("major", 0.0),
                "major",
            ),
        )
        return selected_index, structures[selected_index], "largest_major"

    return 0, structures[0], "first"


def _structure_payload(
    structure: dict[str, Any],
    selected_index: int,
) -> dict[str, Any]:
    anisotropy = structure.get("anisotropy", {})
    ranges = anisotropy.get("ellipsoid_ranges", {})
    rotation = anisotropy.get("rotation", {})

    major = _coerce_structure_float(ranges.get("major", 0.0), "major")
    semi_major = _coerce_structure_float(ranges.get("semi_major", 0.0), "semi_major")
    minor = _coerce_structure_float(ranges.get("minor", 0.0), "minor")

    dip_azimuth = _coerce_structure_float(
        rotation.get("dip_azimuth", 0.0), "dip_azimuth"
    )
    dip = _coerce_structure_float(rotation.get("dip", 0.0), "dip")
    pitch = _coerce_structure_float(rotation.get("pitch", 0.0), "pitch")

    return {
        "structure_index": selected_index,
        "structure_type": structure.get("variogram_type"),
        "contribution": _coerce_structure_float(
            structure.get("contribution", 0.0), "contribution"
        ),
        "alpha": structure.get("alpha"),
        "ranges": {
            "major": major,
            "semi_major": semi_major,
            "minor": minor,
        },
        "rotation": {
            "dip_azimuth": dip_azimuth,
            "dip": dip,
            "pitch": pitch,
        },
        "is_valid_for_ellipsoid": min(major, semi_major, minor) > 0,
        "has_rotation": any(abs(value) > 0 for value in [dip_azimuth, dip, pitch]),
    }


def _principal_direction_curves(
    variogram_data: VariogramData,
    n_points: int,
    max_distance: float | None,
) -> tuple[dict[str, Any], float]:
    structures = variogram_data.get_structures_as_dicts()
    if not structures:
        raise ValueError("variogram_data must contain at least one structure.")

    max_ranges = {"major": 0.0, "semi_major": 0.0, "minor": 0.0}
    for structure in structures:
        anisotropy = structure.get("anisotropy", {})
        ranges = anisotropy.get("ellipsoid_ranges", {})
        for direction in max_ranges:
            max_ranges[direction] = max(
                max_ranges[direction],
                _coerce_structure_float(ranges.get(direction, 0.0), direction),
            )

    resolved_max_distance = max_distance
    if resolved_max_distance is None:
        resolved_max_distance = (
            max(max_ranges.values()) * 1.2 if max(max_ranges.values()) > 0 else 100.0
        )

    h = np.linspace(0.0, resolved_max_distance, n_points)
    curves: dict[str, Any] = {}

    for direction in ["major", "semi_major", "minor"]:
        gamma = np.full_like(h, variogram_data.nugget, dtype=float)
        for structure in structures:
            variogram_type = structure.get("variogram_type", "unknown")
            contribution = _coerce_structure_float(
                structure.get("contribution", 0.0),
                "contribution",
            )
            alpha = structure.get("alpha")
            anisotropy = structure.get("anisotropy", {})
            ranges = anisotropy.get("ellipsoid_ranges", {})
            range_value = _coerce_structure_float(ranges.get(direction, 1.0), direction)

            gamma += _evaluate_structure(
                variogram_type,
                h,
                contribution,
                range_value,
                alpha,
            )

        curves[direction] = {
            "distance": h.tolist(),
            "semivariance": gamma.tolist(),
            "range": max_ranges[direction],
            "final_semivariance": float(gamma[-1]),
        }

    return curves, float(resolved_max_distance)


def register_variogram_tools(mcp) -> None:
    """Register variogram-specific tools with the FastMCP server."""

    @mcp.tool()
    async def variogram_create(
        object_name: str,
        sill: float,
        structures: list[dict[str, Any]],
        nugget: float = 0.0,
        is_rotation_fixed: bool = True,
        modelling_space: Literal["data", "normalscore"] | None = "data",
        data_variance: float | None = None,
        attribute: str | None = None,
        domain: str | None = None,
        description: str | None = None,
        tags: dict[str, str] | None = None,
        extensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a local variogram payload from canonical modelling parameters."""
        if sill <= 0:
            raise ValueError("sill must be greater than zero.")
        if nugget < 0:
            raise ValueError("nugget cannot be negative.")
        parsed_structures = _build_variogram_structures(structures)
        total_contribution = sum(
            structure.contribution for structure in parsed_structures
        )
        if not math.isclose(
            sill,
            nugget + total_contribution,
            rel_tol=1e-6,
            abs_tol=1e-6,
        ):
            raise ValueError(
                "sill must equal nugget + the sum of all structure contributions."
            )

        variogram_data = VariogramData(
            name=object_name,
            description=description,
            tags=tags,
            extensions=extensions,
            sill=sill,
            nugget=nugget,
            is_rotation_fixed=is_rotation_fixed,
            modelling_space=modelling_space,
            data_variance=data_variance if data_variance is not None else sill,
            structures=parsed_structures,
            attribute=attribute,
            domain=domain,
        )
        envelope = staging_service.stage_local_build(
            object_type="variogram",
            typed_payload=variogram_data,
        )
        object_registry.register(
            name=object_name,
            object_type="variogram",
            stage_id=envelope.stage_id,
            summary=envelope.summary,
        )
        return {
            "name": object_name,
            "sill": sill,
            "nugget": nugget,
            "structure_count": len(structures),
            "message": "Variogram created.",
        }

    @mcp.tool()
    async def get_variogram_search_params(
        variogram_name: str | None = None,
        scale_factor: float = 2.0,
        structure_index: int | None = None,
        selection_mode: Literal["first", "largest_major"] = "first",
    ) -> dict[str, Any]:
        """Extract search ellipsoid parameters from a variogram structure and scale them."""
        if scale_factor <= 0:
            raise ValueError("scale_factor must be greater than zero.")

        try:
            _, variogram_data = object_registry.get_payload(
                name=variogram_name, object_type="variogram"
            )
        except (StageError, ResolutionError) as exc:
            raise ValueError(str(exc)) from exc

        structures = variogram_data.get_structures_as_dicts()
        selected_index, selected_structure, selected_by = (
            _select_structure_from_payload(
                structures,
                structure_index,
                selection_mode,
            )
        )
        selected_structure_payload = _structure_payload(
            selected_structure,
            selected_index,
        )

        original_ranges = selected_structure_payload["ranges"]
        scaled_ranges = {
            "major": original_ranges["major"] * scale_factor,
            "semi_major": original_ranges["semi_major"] * scale_factor,
            "minor": original_ranges["minor"] * scale_factor,
        }

        return {
            "variogram_name": variogram_data.name,
            "structure_count": len(structures),
            "selected_structure_index": selected_index,
            "selected_by": selected_by,
            "selection_mode": selection_mode,
            "structure_type": selected_structure_payload["structure_type"],
            "scale_factor": scale_factor,
            "original_ranges": original_ranges,
            "scaled_ranges": scaled_ranges,
            "rotation": selected_structure_payload["rotation"],
            "message": f"Search ellipsoid scaled to {scale_factor}x from selected local variogram structure.",
        }

    @mcp.tool()
    async def get_variogram_structure_details(
        variogram_name: str | None = None,
        structure_index: int | None = None,
        selection_mode: Literal["first", "largest_major"] = "first",
    ) -> dict[str, Any]:
        """Return structure details from a variogram for inspection and selection."""
        try:
            _, variogram_data = object_registry.get_payload(
                name=variogram_name, object_type="variogram"
            )
        except (StageError, ResolutionError) as exc:
            raise ValueError(str(exc)) from exc
        structures = variogram_data.get_structures_as_dicts()
        selected_index, selected_structure, selected_by = (
            _select_structure_from_payload(
                structures,
                structure_index,
                selection_mode,
            )
        )
        structure_details = _structure_payload(selected_structure, selected_index)

        return {
            "variogram_name": variogram_data.name,
            "structure_count": len(structures),
            "selected_structure_index": selected_index,
            "selected_by": selected_by,
            "selection_mode": selection_mode,
            "structure": structure_details,
        }

    @mcp.tool()
    async def get_variogram_ellipsoid_details(
        variogram_name: str | None = None,
        structure_index: int | None = None,
        selection_mode: Literal["first", "largest_major"] = "first",
        center_x: float = 0.0,
        center_y: float = 0.0,
        center_z: float = 0.0,
        include_surface_points: bool = True,
        include_wireframe_points: bool = True,
    ) -> dict[str, Any]:
        """Return ellipsoid details and optional 3D plotting points from a variogram."""
        try:
            _, variogram_data = object_registry.get_payload(
                name=variogram_name, object_type="variogram"
            )
        except (StageError, ResolutionError) as exc:
            raise ValueError(str(exc)) from exc
        structures = variogram_data.get_structures_as_dicts()
        selected_index, selected_structure, selected_by = (
            _select_structure_from_payload(
                structures,
                structure_index,
                selection_mode,
            )
        )
        structure_details = _structure_payload(selected_structure, selected_index)

        result: dict[str, Any] = {
            "variogram_name": variogram_data.name,
            "structure_count": len(structures),
            "selected_structure_index": selected_index,
            "selected_by": selected_by,
            "selection_mode": selection_mode,
            "center": {"x": center_x, "y": center_y, "z": center_z},
            "ranges": structure_details["ranges"],
            "rotation": structure_details["rotation"],
            "is_valid_for_ellipsoid": structure_details["is_valid_for_ellipsoid"],
            "visualization_note": (
                "Use surface_points with plotly Mesh3d(alphahull=0, opacity=0.3) and "
                "wireframe_points with plotly Scatter3d(mode='lines')."
            ),
        }

        if not include_surface_points and not include_wireframe_points:
            return result

        if not structure_details["is_valid_for_ellipsoid"]:
            raise ValueError(
                "Cannot generate ellipsoid points: selected structure has non-positive ranges."
            )

        ranges = structure_details["ranges"]
        rotation = structure_details["rotation"]
        ellipsoid = ComputeEllipsoid(
            ranges=ComputeEllipsoidRanges(
                major=ranges["major"],
                semi_major=ranges["semi_major"],
                minor=ranges["minor"],
            ),
            rotation=ComputeRotation(
                dip_azimuth=rotation["dip_azimuth"],
                dip=rotation["dip"],
                pitch=rotation["pitch"],
            ),
        )

        center = (center_x, center_y, center_z)
        if include_surface_points:
            sx, sy, sz = ellipsoid.surface_points(center=center)
            result["surface_points"] = {
                "x": sx.tolist(),
                "y": sy.tolist(),
                "z": sz.tolist(),
            }
        if include_wireframe_points:
            wx, wy, wz = ellipsoid.wireframe_points(center=center)
            result["wireframe_points"] = {
                "x": wx.tolist(),
                "y": wy.tolist(),
                "z": wz.tolist(),
            }

        return result

    @mcp.tool()
    async def get_variogram_curve_details(
        variogram_name: str | None = None,
        n_points: int = 200,
        max_distance: float | None = None,
        azimuth: float | None = None,
        dip: float | None = None,
    ) -> dict[str, Any]:
        """Return principal-direction curves and optional arbitrary-direction curve from a variogram for 2D plotting."""
        if n_points < 10:
            raise ValueError("n_points must be at least 10.")
        if max_distance is not None and max_distance <= 0:
            raise ValueError("max_distance must be greater than zero when provided.")
        if (azimuth is None) != (dip is None):
            raise ValueError(
                "Provide both azimuth and dip together when requesting arbitrary-direction curves."
            )

        try:
            _, variogram_data = object_registry.get_payload(
                name=variogram_name, object_type="variogram"
            )
        except (StageError, ResolutionError) as exc:
            raise ValueError(str(exc)) from exc

        curves, resolved_max_distance = _principal_direction_curves(
            variogram_data,
            n_points,
            max_distance,
        )

        arbitrary_direction_curve: dict[str, Any] | None = None
        if azimuth is not None and dip is not None:
            structures = variogram_data.get_structures_as_dicts()
            azimuth_rad = math.radians(azimuth)
            dip_rad = math.radians(dip)
            direction = np.array(
                [
                    math.sin(azimuth_rad) * math.cos(dip_rad),
                    math.cos(azimuth_rad) * math.cos(dip_rad),
                    -math.sin(dip_rad),
                ]
            )

            h = np.linspace(0.0, resolved_max_distance, n_points)
            gamma = np.full_like(h, variogram_data.nugget, dtype=float)

            for structure in structures:
                variogram_type = structure.get("variogram_type", "unknown")
                contribution = _coerce_structure_float(
                    structure.get("contribution", 0.0),
                    "contribution",
                )
                alpha = structure.get("alpha")
                anisotropy = structure.get("anisotropy", {})
                ranges = anisotropy.get("ellipsoid_ranges", {})
                rotation_dict = anisotropy.get("rotation", {})

                major = _coerce_structure_float(ranges.get("major", 1.0), "major")
                semi_major = _coerce_structure_float(
                    ranges.get("semi_major", 1.0),
                    "semi_major",
                )
                minor = _coerce_structure_float(ranges.get("minor", 1.0), "minor")

                effective_range = major
                if major > 0 and semi_major > 0 and minor > 0:
                    rotation = Rotation(
                        dip_azimuth=_coerce_structure_float(
                            rotation_dict.get("dip_azimuth", 0.0),
                            "dip_azimuth",
                        ),
                        dip=_coerce_structure_float(
                            rotation_dict.get("dip", 0.0), "dip"
                        ),
                        pitch=_coerce_structure_float(
                            rotation_dict.get("pitch", 0.0),
                            "pitch",
                        ),
                    )
                    local_direction = rotation.as_rotation_matrix().T @ direction
                    scaled_direction = np.array(
                        [
                            local_direction[0] / major,
                            local_direction[1] / semi_major,
                            local_direction[2] / minor,
                        ]
                    )
                    direction_norm = np.linalg.norm(scaled_direction)
                    if direction_norm > 0:
                        effective_range = 1.0 / direction_norm

                gamma += _evaluate_structure(
                    variogram_type,
                    h,
                    contribution,
                    effective_range,
                    alpha,
                )

            arbitrary_direction_curve = {
                "azimuth": azimuth,
                "dip": dip,
                "distance": h.tolist(),
                "semivariance": gamma.tolist(),
                "final_semivariance": float(gamma[-1]),
            }

        return {
            "variogram_name": variogram_data.name,
            "sample_count": n_points,
            "max_distance": resolved_max_distance,
            "sill": variogram_data.sill,
            "nugget": variogram_data.nugget,
            "variogram_curves": curves,
            "arbitrary_direction_curve": arbitrary_direction_curve,
            "visualization_note": (
                "Use variogram_curves with plotly Scatter for principal direction 2D charts, add a horizontal sill reference line, "
                "and optionally plot arbitrary_direction_curve when azimuth and dip are provided."
            ),
        }
