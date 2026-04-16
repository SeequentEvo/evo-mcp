# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Point set staged object type with discoverable interactions.

Interactions:
  - create: Build a local PointSet from CSV data.
  - summarize: Return geometry summary and bounding box.
  - attribute_details: Inspect attribute columns with statistics.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Union

import pandas as pd
from evo.objects.typed import EpsgCode, PointSet, PointSetData
from pydantic import BaseModel, ConfigDict, Field

from evo_mcp.staging.errors import StageValidationError
from evo_mcp.staging.objects.base import (
    Interaction,
    StagedObjectType,
    staged_object_type_registry,
)
from evo_mcp.staging.runtime import get_registry, get_staging_service
from evo_mcp.utils.tool_support import extract_crs, format_crs, resolve_crs


def _resolve_point_set_crs(
    coordinate_reference_system: Any,
    *,
    none_value: Any = None,
) -> EpsgCode | str | None:
    resolved = resolve_crs(coordinate_reference_system, none_value=none_value)
    if resolved == none_value:
        return none_value
    if isinstance(resolved, int):
        return EpsgCode(resolved)
    return resolved


# ── Interaction parameter model ───────────────────────────────────────────────


class PointSetCreateParams(BaseModel):
    model_config = ConfigDict(extra="ignore")

    object_name: str = Field(..., description="Name for the new point set.")
    csv_file: str = Field(
        ..., description="Path to the CSV file containing point data."
    )
    x_column: str = Field(..., description="Column name for X coordinates.")
    y_column: str = Field(..., description="Column name for Y coordinates.")
    z_column: str = Field(..., description="Column name for Z coordinates.")
    attribute_columns: list[str] = Field(
        default_factory=list,
        description="Columns to include as attributes. Empty list auto-detects all non-coordinate columns.",
    )
    description: str | None = Field(None, description="Object description.")
    tags: dict[str, Any] | None = Field(None, description="Tags dict.")
    coordinate_reference_system: Union[str, int] = Field(
        "unspecified",
        description="CRS as 'unspecified', an EPSG integer, or 'EPSG:NNNN' string.",
    )
    coordinate_cleaning: Literal["drop_invalid"] = Field(
        "drop_invalid",
        description="Strategy for rows with invalid or missing coordinates.",
    )


def _point_set_summary(df: pd.DataFrame) -> dict[str, Any]:
    if len(df) == 0:
        raise ValueError("PointSet data is empty.")
    return {
        "point_count": int(len(df)),
        "attribute_count": int(max(0, len(df.columns) - 3)),
        "attribute_names": [col for col in df.columns if col not in {"x", "y", "z"}],
        "bounding_box": {
            "min_x": float(df["x"].min()),
            "max_x": float(df["x"].max()),
            "min_y": float(df["y"].min()),
            "max_y": float(df["y"].max()),
            "min_z": float(df["z"].min()),
            "max_z": float(df["z"].max()),
        },
    }


def _attribute_inspection(df: pd.DataFrame) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    for col in df.columns:
        if col in {"x", "y", "z"}:
            continue
        series = df[col]
        details.append(
            {
                "name": col,
                "dtype": str(series.dtype),
                "null_count": int(series.isna().sum()),
                "is_numeric": bool(pd.api.types.is_numeric_dtype(series)),
                "preview_values": series.dropna().head(5).tolist(),
            }
        )
    return details


# ── Interaction handlers ──────────────────────────────────────────────────────


async def _summarize(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    df = payload.locations
    summary = _point_set_summary(df)
    return {
        "name": payload.name,
        "coordinate_reference_system": payload.coordinate_reference_system,
        "summary": summary,
    }


async def _attribute_details(payload: Any, params: dict[str, Any]) -> dict[str, Any]:
    df = payload.locations
    return {
        "name": payload.name,
        "point_count": int(len(df)),
        "attribute_details": _attribute_inspection(df),
    }


# ── Create interaction handler ─────────────────────────────────────────────────


async def _create(params: PointSetCreateParams) -> dict[str, Any]:
    """Build a local PointSet payload from CSV data."""
    csv_path = Path(params.csv_file)
    if not csv_path.exists():
        raise ValueError(f"CSV file not found: {params.csv_file}")

    df = pd.read_csv(csv_path)
    required_columns = [params.x_column, params.y_column, params.z_column]
    missing_required = [c for c in required_columns if c not in df.columns]
    if missing_required:
        raise ValueError(f"Missing required coordinate columns: {missing_required}")

    selected_attribute_columns = params.attribute_columns or [
        c for c in df.columns if c not in required_columns
    ]
    missing_attributes = [c for c in selected_attribute_columns if c not in df.columns]
    if missing_attributes:
        raise ValueError(
            f"Specified attribute columns were not found in CSV: {missing_attributes}"
        )

    selected_columns = required_columns + selected_attribute_columns
    working_df = df[selected_columns].copy()
    working_df = working_df.rename(
        columns={params.x_column: "x", params.y_column: "y", params.z_column: "z"}
    )

    for coord_col in ["x", "y", "z"]:
        working_df[coord_col] = pd.to_numeric(working_df[coord_col], errors="coerce")

    invalid_mask = working_df[["x", "y", "z"]].isna().any(axis=1)
    invalid_count = int(invalid_mask.sum())
    working_df = working_df[~invalid_mask].copy()

    if len(working_df) == 0:
        raise ValueError("No valid points remain after coordinate validation.")

    resolved_crs = _resolve_point_set_crs(
        params.coordinate_reference_system,
        none_value=None,
    )

    point_set_data = PointSetData(
        name=params.object_name,
        description=params.description,
        tags=params.tags,
        coordinate_reference_system=resolved_crs,
        locations=working_df,
    )

    summary = _point_set_summary(point_set_data.locations)
    summary["source_rows"] = int(len(df))
    summary["dropped_invalid_coordinate_rows"] = invalid_count

    envelope = get_staging_service().stage_local_build(
        object_type="point_set",
        typed_payload=point_set_data,
    )
    get_registry().register(
        name=params.object_name,
        object_type="point_set",
        stage_id=envelope.stage_id,
        summary=summary,
    )
    return {
        "name": params.object_name,
        "summary": summary,
        "message": "Point set created.",
    }


# ── Import / publish handlers ─────────────────────────────────────────────────


async def _import_point_set(obj: Any, context: Any) -> tuple[Any, dict[str, Any], str]:
    dataframe = await obj.to_dataframe()
    data = PointSetData(
        name=obj.name,
        description=getattr(obj, "description", None),
        coordinate_reference_system=format_crs(extract_crs(obj)),
        locations=dataframe,
    )
    return data, {}, "Point set imported."


# ── Object type definition ────────────────────────────────────────────────────


class PointSetObjectType(StagedObjectType):
    """Staged point set with geometry and attribute inspection interactions."""

    object_type = "point_set"
    display_name = "Point Set"
    evo_class = PointSet
    data_classes = (PointSetData,)
    supported_publish_modes = frozenset({"create", "new_version"})
    fixture_path_segment = "pointsets"
    role_label = "PointSet"
    role_article = "a PointSet"
    create_params_model = PointSetCreateParams

    def _validate(self, payload: PointSetData) -> None:
        df = payload.locations
        if df is None or len(df) == 0:
            raise StageValidationError("PointSetData locations must be non-empty.")
        for col in ("x", "y", "z"):
            if col not in df.columns:
                raise StageValidationError(
                    f"PointSetData locations must contain column '{col}'."
                )

    def summarize(self, payload: PointSetData) -> dict[str, Any]:
        df = payload.locations
        attribute_names = [c for c in df.columns if c not in {"x", "y", "z"}]
        return {
            "point_count": int(len(df)),
            "attribute_count": len(attribute_names),
            "attribute_names": attribute_names,
            "coordinate_reference_system": payload.coordinate_reference_system,
        }

    def from_dict(self, data: dict[str, Any]) -> PointSetData:
        raw = data.get("data", {})
        coords = raw.get("coordinates", {})
        try:
            df = pd.DataFrame(
                {
                    "x": pd.to_numeric(pd.Series(coords["x"]), errors="raise").astype(
                        "float64"
                    ),
                    "y": pd.to_numeric(pd.Series(coords["y"]), errors="raise").astype(
                        "float64"
                    ),
                    "z": pd.to_numeric(pd.Series(coords["z"]), errors="raise").astype(
                        "float64"
                    ),
                }
            )
        except KeyError as exc:
            raise StageValidationError(
                f"PointSetData dict is missing required coordinate key: {exc}"
            ) from exc
        for attr_name, attr_values in (raw.get("attributes") or {}).items():
            df[attr_name] = pd.Series(attr_values)
        try:
            name = data["name"]
        except KeyError as exc:
            raise StageValidationError(
                "PointSetData dict is missing required key 'name'."
            ) from exc

        try:
            resolved_crs = _resolve_point_set_crs(
                data.get("coordinate_reference_system"),
                none_value=None,
            )
        except ValueError as exc:
            raise StageValidationError(f"Invalid point set CRS: {exc}") from exc

        return PointSetData(
            name=name,
            description=data.get("description"),
            tags=data.get("tags") or {},
            coordinate_reference_system=resolved_crs,
            locations=df,
        )

    async def create(self, params: PointSetCreateParams) -> dict[str, Any]:
        return await _create(params)

    def __init__(self) -> None:
        super().__init__()
        self._register_interaction(
            Interaction(
                name="get_summary",
                display_name="Get Summary",
                description="Return point count, attribute names, and bounding box.",
                handler=_summarize,
            )
        )
        self._register_interaction(
            Interaction(
                name="get_attribute_details",
                display_name="Get Attribute Details",
                description="Inspect each attribute column: dtype, null count, numeric status, and value preview.",
                handler=_attribute_details,
            )
        )

    async def import_handler(self, obj, context):
        return await _import_point_set(obj, context)

    async def publish_create(self, context, data, path):
        return await PointSet.create(context, data, path=path)

    async def publish_replace(self, context, url, data):
        return await PointSet.replace(context, url, data)


# Auto-register at import time.
staged_object_type_registry.register(PointSetObjectType())
