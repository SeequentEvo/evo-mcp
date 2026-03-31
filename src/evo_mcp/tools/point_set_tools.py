# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""MCP tools for local PointSet workflows.

Tools for building and inspecting point set data. Objects are tracked
by name via the session registry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import pandas as pd
from evo.objects.typed import EpsgCode, PointSetData

from evo_mcp.session import object_registry, ResolutionError
from evo_mcp.staging.errors import StageError
from evo_mcp.staging.service import staging_service
from evo_mcp.utils.tool_support import (
    normalize_crs,
)


def _point_set_data_model_from_payload(point_set_data: dict[str, Any]) -> PointSetData:
    data = point_set_data.get("data")
    if not isinstance(data, dict):
        raise ValueError("point_set_data.data is required and must be an object.")

    coordinates = data.get("coordinates")
    if not isinstance(coordinates, dict):
        raise ValueError(
            "point_set_data.data.coordinates is required and must be an object."
        )

    x = coordinates.get("x")
    y = coordinates.get("y")
    z = coordinates.get("z")
    if not isinstance(x, list) or not isinstance(y, list) or not isinstance(z, list):
        raise ValueError(
            "point_set_data.data.coordinates.x/y/z must each be provided as arrays."
        )

    if len(x) != len(y) or len(y) != len(z):
        raise ValueError("Coordinate arrays x/y/z must have identical lengths.")

    df = pd.DataFrame(
        {
            "x": pd.to_numeric(pd.Series(x), errors="raise").astype("float64"),
            "y": pd.to_numeric(pd.Series(y), errors="raise").astype("float64"),
            "z": pd.to_numeric(pd.Series(z), errors="raise").astype("float64"),
        }
    )

    attributes = data.get("attributes") or {}
    if not isinstance(attributes, dict):
        raise ValueError(
            "point_set_data.data.attributes must be an object when provided."
        )

    for attribute_name, attribute_values in attributes.items():
        if not isinstance(attribute_values, list):
            raise ValueError(
                f"Attribute '{attribute_name}' values must be an array in point_set_data."
            )
        if len(attribute_values) != len(df):
            raise ValueError(
                f"Attribute '{attribute_name}' length ({len(attribute_values)}) does not match coordinate length ({len(df)})."
            )
        df[attribute_name] = pd.Series(attribute_values)

    return PointSetData(
        name=str(point_set_data.get("name") or "PointSet"),
        description=point_set_data.get("description"),
        tags=point_set_data.get("tags"),
        coordinate_reference_system=normalize_crs(
            point_set_data.get("coordinate_reference_system", "unspecified")
        ),
        locations=df,
    )


def _point_set_summary(df: pd.DataFrame) -> dict[str, Any]:
    if len(df) == 0:
        raise ValueError("PointSet data is empty.")

    result = {
        "point_count": int(len(df)),
        "attribute_count": int(max(0, len(df.columns) - 3)),
        "attribute_names": [
            column for column in df.columns if column not in {"x", "y", "z"}
        ],
        "bounding_box": {
            "min_x": float(df["x"].min()),
            "max_x": float(df["x"].max()),
            "min_y": float(df["y"].min()),
            "max_y": float(df["y"].max()),
            "min_z": float(df["z"].min()),
            "max_z": float(df["z"].max()),
        },
    }
    return result


def _attribute_inspection(df: pd.DataFrame) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for column in df.columns:
        if column in {"x", "y", "z"}:
            continue
        series = df[column]
        value_preview = series.dropna().head(5).tolist()
        details.append(
            {
                "name": column,
                "dtype": str(series.dtype),
                "null_count": int(series.isna().sum()),
                "is_numeric": bool(pd.api.types.is_numeric_dtype(series)),
                "preview_values": value_preview,
            }
        )
    return details


def register_point_set_tools(mcp) -> None:
    """Register point-set-specific tools with the FastMCP server."""

    @mcp.tool()
    async def point_set_build_local(
        object_name: str,
        csv_file: str,
        x_column: str,
        y_column: str,
        z_column: str,
        attribute_columns: list[str] | None = None,
        description: str | None = None,
        tags: dict[str, str] | None = None,
        coordinate_reference_system: str = "unspecified",
        coordinate_cleaning: Literal["drop_invalid"] = "drop_invalid",
    ) -> dict[str, Any]:
        """Build a local PointSet payload from CSV data without publishing to Evo."""
        valid_cleaning_modes = {"drop_invalid"}
        if coordinate_cleaning not in valid_cleaning_modes:
            raise ValueError(
                f"Invalid coordinate_cleaning mode '{coordinate_cleaning}'. "
                "Valid options are: 'drop_invalid' or omit the parameter to raise on invalid coordinates."
            )

        if attribute_columns is None:
            attribute_columns = []

        csv_path = Path(csv_file)
        if not csv_path.exists():
            raise ValueError(f"CSV file not found: {csv_file}")

        df = pd.read_csv(csv_path)

        required_columns = [x_column, y_column, z_column]
        missing_required = [
            column for column in required_columns if column not in df.columns
        ]
        if missing_required:
            raise ValueError(f"Missing required coordinate columns: {missing_required}")

        selected_attribute_columns = attribute_columns
        if len(selected_attribute_columns) == 0:
            selected_attribute_columns = [
                column for column in df.columns if column not in required_columns
            ]

        missing_attributes = [
            column for column in selected_attribute_columns if column not in df.columns
        ]
        if missing_attributes:
            raise ValueError(
                f"Specified attribute columns were not found in CSV: {missing_attributes}"
            )

        selected_columns = required_columns + selected_attribute_columns
        working_df = df[selected_columns].copy()
        working_df = working_df.rename(
            columns={x_column: "x", y_column: "y", z_column: "z"}
        )

        for coordinate_column in ["x", "y", "z"]:
            working_df[coordinate_column] = pd.to_numeric(
                working_df[coordinate_column],
                errors="coerce",
            )

        invalid_coordinate_mask = working_df[["x", "y", "z"]].isna().any(axis=1)
        invalid_coordinate_count = int(invalid_coordinate_mask.sum())

        if coordinate_cleaning == "drop_invalid":
            working_df = working_df[~invalid_coordinate_mask].copy()
        elif invalid_coordinate_count > 0:
            raise ValueError(
                "Coordinate columns contain invalid or missing values. "
                "Use coordinate_cleaning='drop_invalid' to filter those rows."
            )

        if len(working_df) == 0:
            raise ValueError("No valid points remain after coordinate validation.")

        resolved_crs = normalize_crs(coordinate_reference_system, none_value=None)
        if isinstance(resolved_crs, str) and resolved_crs.upper().startswith("EPSG:"):
            try:
                resolved_crs = EpsgCode(int(resolved_crs.split(":", 1)[1]))
            except (ValueError, IndexError):
                pass
        point_set_data_model = PointSetData(
            name=object_name,
            description=description,
            tags=tags,
            coordinate_reference_system=resolved_crs,
            locations=working_df,
        )

        summary = _point_set_summary(point_set_data_model.locations)
        summary["source_rows"] = int(len(df))
        summary["dropped_invalid_coordinate_rows"] = invalid_coordinate_count

        envelope = staging_service.stage_local_build(
            object_type="point_set",
            typed_payload=point_set_data_model,
        )

        object_registry.register(
            name=object_name,
            object_type="point_set",
            stage_id=envelope.stage_id,
            summary=summary,
        )

        return {
            "name": object_name,
            "summary": summary,
            "message": "Point set created.",
        }

    @mcp.tool()
    async def point_set_summarize(
        point_set_name: str | None = None,
    ) -> dict[str, Any]:
        """Summarize point set geometry and attribute counts."""
        try:
            entry, point_set_data_model = object_registry.get_payload(
                name=point_set_name, object_type="point_set"
            )
        except (StageError, ResolutionError) as exc:
            raise ValueError(str(exc)) from exc
        summary = dict(entry.summary)
        summary["bounding_box"] = _point_set_summary(point_set_data_model.locations).get("bounding_box")
        return {
            "name": point_set_data_model.name,
            "coordinate_reference_system": point_set_data_model.coordinate_reference_system,
            "summary": summary,
        }

    @mcp.tool()
    async def point_set_attribute_details(
        point_set_name: str | None = None,
    ) -> dict[str, Any]:
        """Inspect attribute columns of a point set."""
        try:
            _, point_set_data_model = object_registry.get_payload(
                name=point_set_name, object_type="point_set"
            )
        except (StageError, ResolutionError) as exc:
            raise ValueError(str(exc)) from exc
        df = point_set_data_model.locations
        return {
            "name": point_set_data_model.name,
            "point_count": int(len(df)),
            "attribute_details": _attribute_inspection(df),
        }
