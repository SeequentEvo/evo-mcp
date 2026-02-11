"""
MCP tools for building and creating Geoscience Objects from CSV data.

This module provides high-level tools for creating:
- Pointsets: Point clouds with X/Y/Z coordinates and attributes
- LineSegments: Line segments defined by vertices and indices
- DownholeCollections: Drillhole data with collars, surveys, and intervals

All tools follow a similar pattern:
1. Load and validate CSV data
2. Build schema-compliant objects
3. Validate against Geoscience Object Model schemas
4. Upload data and create objects in Evo workspace (if not dry_run)
"""

import logging
from pathlib import Path
from uuid import UUID

import pandas as pd

from evo.common.utils import Cache
from evo_mcp.context import evo_context, ensure_initialized
from evo_mcp.utils.object_builders import (
    PointsetBuilder,
    LineSegmentsBuilder,
    DownholeCollectionBuilder,
    DownholeIntervalsBuilder,
)
from evo_schemas.objects.pointset import Pointset_V1_3_0
from evo_schemas.objects.line_segments import LineSegments_V2_2_0
from evo_schemas.objects.downhole_collection import DownholeCollection_V1_3_0
from evo_schemas.objects.downhole_intervals import DownholeIntervals_V1_3_0

logger = logging.getLogger(__name__)


def register_object_builder_tools(mcp):
    """Register all object builder tools."""
    
    @mcp.tool()
    async def build_and_create_pointset(
        workspace_id: str,
        object_path: str,
        object_name: str,
        description: str,
        csv_file: str,
        x_column: str,
        y_column: str,
        z_column: str,
        attribute_columns: list[str] = [],
        tags: dict = {},
        coordinate_reference_system: str = "unspecified",
        dry_run: bool = True,
    ) -> dict:
        """Build and create a Pointset object from a CSV file.
        
        A Pointset is a set of points in 3D space with optional attributes.
        Common uses: sample locations, sensor positions, survey points.
        
        Args:
            workspace_id: Target Evo workspace UUID
            object_path: Path for the new object (e.g., "/samples/locations.json")
            object_name: Display name for the object
            description: Object description
            csv_file: Path to CSV file with point data
            x_column: X coordinate column name
            y_column: Y coordinate column name
            z_column: Z coordinate column name
            attribute_columns: Columns to include as attributes (empty = auto-detect all)
            tags: Optional tags dictionary
            coordinate_reference_system: CRS string (default: "unspecified")
            dry_run: If True, validate only without creating (default: True)
        
        Returns:
            Dict with validation results and object info
        """
        result = {"errors": [], "warnings": [], "data_summary": {}}
        
        # Load CSV
        try:
            csv_path = Path(csv_file)
            if not csv_path.exists():
                return {"status": "error", "error": f"CSV file not found: {csv_file}"}
            df = pd.read_csv(csv_path)
            result["data_summary"]["rows"] = len(df)
            result["data_summary"]["columns"] = list(df.columns)
        except Exception as e:
            return {"status": "error", "error": f"Failed to read CSV file: {e}"}
        
        # Validate required columns
        required = [x_column, y_column, z_column]
        missing = [c for c in required if c not in df.columns]
        if missing:
            result["errors"].append(f"Missing required columns: {missing}")
            return {"status": "validation_failed", "validation": result}
        
        # Clean string columns
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].fillna('').astype(str)
        
        # Check NaN in coordinates
        coord_cols = [x_column, y_column, z_column]
        nan_count = df[coord_cols].isna().any(axis=1).sum()
        if nan_count > 0:
            result["warnings"].append(f"{nan_count} rows have NaN coordinates")
        if nan_count == len(df):
            result["errors"].append("All rows have NaN coordinates")
            return {"status": "validation_failed", "validation": result}
        
        # Calculate bounding box for preview
        try:
            valid_mask = df[coord_cols].notna().all(axis=1)
            valid_df = df[valid_mask]
            result["data_summary"]["bounding_box"] = {
                "min_x": float(valid_df[x_column].min()),
                "max_x": float(valid_df[x_column].max()),
                "min_y": float(valid_df[y_column].min()),
                "max_y": float(valid_df[y_column].max()),
                "min_z": float(valid_df[z_column].min()),
                "max_z": float(valid_df[z_column].max()),
            }
            result["data_summary"]["valid_points"] = len(valid_df)
        except Exception as e:
            result["errors"].append(f"Failed to calculate bounding box: {e}")
            return {"status": "validation_failed", "validation": result}
        
        # Determine attribute columns
        attr_cols = attribute_columns if attribute_columns else None
        if attr_cols is None:
            auto_attrs = [c for c in df.columns if c not in coord_cols]
            result["data_summary"]["auto_detected_attributes"] = auto_attrs
        else:
            result["data_summary"]["specified_attributes"] = attr_cols
        
        if dry_run:
            return {
                "status": "validation_passed",
                "message": "Dry run passed. Set dry_run=False to create the object.",
                "validation": result,
                "object_preview": {
                    "name": object_name,
                    "path": object_path,
                    "points": result["data_summary"]["valid_points"],
                    "attributes": attr_cols or auto_attrs,
                }
            }
        
        # Create the object
        await ensure_initialized()
        
        try:
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            _cache = Cache(evo_context.cache_path)
            data_client = object_client.get_data_client(_cache)
            
            builder = PointsetBuilder(data_client)
            
            obj = builder.build(
                name=object_name,
                df=df,
                x_column=x_column,
                y_column=y_column,
                z_column=z_column,
                attribute_columns=attr_cols,
                description=description,
                tags=tags,
                crs=coordinate_reference_system,
            )
            
            obj_dict = obj.as_dict()
            
            # Validate by reconstructing
            try:
                Pointset_V1_3_0.from_dict(obj_dict)
            except Exception as e:
                return {
                    "status": "schema_validation_failed",
                    "error": str(e),
                    "validation": result,
                }
            
            await data_client.upload_referenced_data(obj_dict)
            metadata = await object_client.create_geoscience_object(object_path, obj_dict)
            
            return {
                "status": "created",
                "object_id": str(metadata.id),
                "name": metadata.name,
                "path": metadata.path,
                "version_id": metadata.version_id,
                "validation": result,
                "builder_warnings": builder.warnings,
            }
            
        except Exception as e:
            logger.exception("Failed to create pointset")
            return {"status": "creation_failed", "error": str(e), "validation": result}
    
    @mcp.tool()
    async def build_and_create_line_segments(
        workspace_id: str,
        object_path: str,
        object_name: str,
        description: str,
        vertices_file: str,
        segments_file: str,
        x_column: str,
        y_column: str,
        z_column: str,
        start_index_column: str,
        end_index_column: str,
        vertex_attribute_columns: list[str] = [],
        segment_attribute_columns: list[str] = [],
        tags: dict = {},
        coordinate_reference_system: str = "unspecified",
        dry_run: bool = True,
    ) -> dict:
        """Build and create a LineSegments object from CSV files.
        
        A LineSegments object is a collection of line segments in 3D space.
        Common uses: fault traces, geological contacts, survey lines.
        
        Requires two CSV files:
        - vertices_file: Contains X/Y/Z coordinates for each vertex (row 0 = vertex index 0)
        - segments_file: Contains start/end vertex indices defining each segment
        
        Args:
            workspace_id: Target Evo workspace UUID
            object_path: Path for the new object (e.g., "/lines/faults.json")
            object_name: Display name for the object
            description: Object description
            vertices_file: Path to CSV with vertex coordinates
            segments_file: Path to CSV with segment definitions
            x_column: X coordinate column name in vertices
            y_column: Y coordinate column name in vertices
            z_column: Z coordinate column name in vertices
            start_index_column: Start vertex index column in segments
            end_index_column: End vertex index column in segments
            vertex_attribute_columns: Vertex attributes (empty = auto-detect)
            segment_attribute_columns: Segment attributes (empty = auto-detect)
            tags: Optional tags dictionary
            coordinate_reference_system: CRS string (default: "unspecified")
            dry_run: If True, validate only without creating (default: True)
        
        Returns:
            Dict with validation results and object info
        """
        result = {"errors": [], "warnings": [], "data_summary": {}}
        
        # Load vertices
        try:
            vertices_path = Path(vertices_file)
            if not vertices_path.exists():
                return {"status": "error", "error": f"Vertices file not found: {vertices_file}"}
            vertices_df = pd.read_csv(vertices_path)
            result["data_summary"]["vertices"] = len(vertices_df)
            result["data_summary"]["vertex_columns"] = list(vertices_df.columns)
        except Exception as e:
            return {"status": "error", "error": f"Failed to read vertices file: {e}"}
        
        # Load segments
        try:
            segments_path = Path(segments_file)
            if not segments_path.exists():
                return {"status": "error", "error": f"Segments file not found: {segments_file}"}
            segments_df = pd.read_csv(segments_path)
            result["data_summary"]["segments"] = len(segments_df)
            result["data_summary"]["segment_columns"] = list(segments_df.columns)
        except Exception as e:
            return {"status": "error", "error": f"Failed to read segments file: {e}"}
        
        # Validate required columns
        required_vertex = [x_column, y_column, z_column]
        missing = [c for c in required_vertex if c not in vertices_df.columns]
        if missing:
            result["errors"].append(f"Missing vertex columns: {missing}")
        
        required_segment = [start_index_column, end_index_column]
        missing = [c for c in required_segment if c not in segments_df.columns]
        if missing:
            result["errors"].append(f"Missing segment columns: {missing}")
        
        if result["errors"]:
            return {"status": "validation_failed", "validation": result}
        
        # Clean string columns
        for df in [vertices_df, segments_df]:
            for col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].fillna('').astype(str)
        
        # Validate segment indices
        max_vertex_idx = len(vertices_df) - 1
        start_max = segments_df[start_index_column].max()
        end_max = segments_df[end_index_column].max()
        if start_max > max_vertex_idx or end_max > max_vertex_idx:
            result["errors"].append(
                f"Segment indices exceed vertex count. Max valid index: {max_vertex_idx}, "
                f"found start max: {start_max}, end max: {end_max}"
            )
            return {"status": "validation_failed", "validation": result}
        
        # Calculate bounding box
        try:
            coord_cols = [x_column, y_column, z_column]
            valid_mask = vertices_df[coord_cols].notna().all(axis=1)
            valid_df = vertices_df[valid_mask]
            if len(valid_df) == 0:
                result["errors"].append("No valid vertex coordinates found")
                return {"status": "validation_failed", "validation": result}
            
            result["data_summary"]["bounding_box"] = {
                "min_x": float(valid_df[x_column].min()),
                "max_x": float(valid_df[x_column].max()),
                "min_y": float(valid_df[y_column].min()),
                "max_y": float(valid_df[y_column].max()),
                "min_z": float(valid_df[z_column].min()),
                "max_z": float(valid_df[z_column].max()),
            }
        except Exception as e:
            result["errors"].append(f"Failed to calculate bounding box: {e}")
            return {"status": "validation_failed", "validation": result}
        
        if dry_run:
            return {
                "status": "validation_passed",
                "message": "Dry run passed. Set dry_run=False to create the object.",
                "validation": result,
                "object_preview": {
                    "name": object_name,
                    "path": object_path,
                    "vertices": len(vertices_df),
                    "segments": len(segments_df),
                }
            }
        
        # Create the object
        await ensure_initialized()
        
        try:
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            _cache = Cache(evo_context.cache_path)
            data_client = object_client.get_data_client(_cache)
            
            builder = LineSegmentsBuilder(data_client)
            
            obj = builder.build(
                name=object_name,
                vertices_df=vertices_df,
                segments_df=segments_df,
                x_column=x_column,
                y_column=y_column,
                z_column=z_column,
                start_index_column=start_index_column,
                end_index_column=end_index_column,
                vertex_attribute_columns=vertex_attribute_columns if vertex_attribute_columns else None,
                segment_attribute_columns=segment_attribute_columns if segment_attribute_columns else None,
                description=description,
                tags=tags,
                crs=coordinate_reference_system,
            )
            
            obj_dict = obj.as_dict()
            
            # Validate by reconstructing
            try:
                LineSegments_V2_2_0.from_dict(obj_dict)
            except Exception as e:
                return {
                    "status": "schema_validation_failed",
                    "error": str(e),
                    "validation": result,
                }
            
            await data_client.upload_referenced_data(obj_dict)
            metadata = await object_client.create_geoscience_object(object_path, obj_dict)
            
            return {
                "status": "created",
                "object_id": str(metadata.id),
                "name": metadata.name,
                "path": metadata.path,
                "version_id": metadata.version_id,
                "validation": result,
                "builder_warnings": builder.warnings,
            }
            
        except Exception as e:
            logger.exception("Failed to create line segments")
            return {"status": "creation_failed", "error": str(e), "validation": result}
    
    @mcp.tool()
    async def build_and_create_downhole_collection(
        workspace_id: str,
        object_path: str,
        object_name: str,
        description: str,
        collar_file: str,
        survey_file: str,
        collar_id_column: str,
        survey_id_column: str,
        x_column: str,
        y_column: str,
        z_column: str,
        depth_column: str,
        azimuth_column: str,
        dip_column: str,        
        max_depth_column: Optional[str] = None,
        interval_files: list[dict] = [],
        tags: dict = {},
        coordinate_reference_system: str = "unspecified",
        invert_z: bool = False,
        dry_run: bool = True,
    ) -> dict:
        """Build and create a DownholeCollection object from CSV files.
        
        This is a high-level tool that:
        1. Reads and validates all CSV files
        2. Constructs the complete object with proper schema structure
        3. Uploads all data blobs (parquet files)
        4. Validates the final object against the schema
        5. Creates the object in the workspace (if not dry_run)
        
        Args:
            workspace_id: Target Evo workspace UUID
            object_path: Path for the new object (e.g., "/drillholes/my_data.json")
            object_name: Display name for the object
            description: Object description
            collar_file: Path to collar CSV file
            survey_file: Path to survey CSV file
            collar_id_column: Hole ID column name in collar file
            survey_id_column: Hole ID column name in survey file
            x_column: X coordinate column in collar
            y_column: Y coordinate column in collar
            z_column: Z coordinate column in collar
            depth_column: Depth/distance column in survey
            azimuth_column: Azimuth column in survey
            dip_column: Dip column in survey            
            max_depth_column: Max depth column in collar file (optional - if not provided, 
                will be calculated from survey data)
            interval_files: List of interval file configs, each with:
                - file: Path to CSV file
                - name: Collection name (e.g., "assay", "geology")
                - id_column: Hole ID column name
                - from_column: From depth column name
                - to_column: To depth column name
                - attribute_columns: (optional) List of columns to include as attributes
            tags: Optional tags dictionary
            coordinate_reference_system: CRS string (default: "unspecified")
            invert_z: If True, negate dip values in survey data. Set depending on the convention followed. Default: False.
            dry_run: If True, validate only without creating (default: True)
        
        Returns:
            Dict with validation results and object info (or creation result if not dry_run)
        """
        result = {"errors": [], "warnings": [], "data_summary": {}}
        
        # Load collar file
        try:
            collar_path = Path(collar_file)
            if not collar_path.exists():
                return {"status": "error", "error": f"Collar file not found: {collar_file}"}
            collar_df = pd.read_csv(collar_path)
            result["data_summary"]["collar_rows"] = len(collar_df)
        except Exception as e:
            return {"status": "error", "error": f"Failed to read collar file: {e}"}
        
        # Load survey file
        try:
            survey_path = Path(survey_file)
            if not survey_path.exists():
                return {"status": "error", "error": f"Survey file not found: {survey_file}"}
            survey_df = pd.read_csv(survey_path)
            result["data_summary"]["survey_rows"] = len(survey_df)
        except Exception as e:
            return {"status": "error", "error": f"Failed to read survey file: {e}"}
        
        # Validate required columns
        required_collar = [collar_id_column, x_column, y_column, z_column]
        missing = [c for c in required_collar if c not in collar_df.columns]
        if missing:
            result["errors"].append(f"Missing collar columns: {missing}")
        
        # Validate max_depth_column if provided
        if max_depth_column and max_depth_column not in collar_df.columns:
            result["errors"].append(f"Max depth column '{max_depth_column}' not found in collar file")
        
        required_survey = [survey_id_column, depth_column, azimuth_column, dip_column]
        missing = [c for c in required_survey if c not in survey_df.columns]
        if missing:
            result["errors"].append(f"Missing survey columns: {missing}")
        
        if result["errors"]:
            return {"status": "validation_failed", "validation": result}
        
        # Clean string columns
        for df in [collar_df, survey_df]:
            for col in df.columns:
                if df[col].dtype == 'object':
                    df[col] = df[col].fillna('').astype(str)
        
        # Check NaN in coordinates
        coord_cols = [x_column, y_column, z_column]
        nan_count = collar_df[coord_cols].isna().any(axis=1).sum()
        if nan_count > 0:
            result["warnings"].append(
                f"{nan_count} collar rows have NaN coordinates (excluded from bounding box)"
            )
        if nan_count == len(collar_df):
            result["errors"].append("All collar rows have NaN coordinates")
            return {"status": "validation_failed", "validation": result}
        
        # Count unique holes
        unique_holes = collar_df[collar_id_column].nunique()
        if len(collar_df) != unique_holes:
            result["warnings"].append(
                f"Collar has duplicate hole IDs: {len(collar_df)} rows, {unique_holes} unique"
            )
        result["data_summary"]["unique_holes"] = unique_holes
        
        # Calculate bounding box for preview
        try:
            valid_mask = collar_df[coord_cols].notna().all(axis=1)
            valid_collar = collar_df[valid_mask]
            result["data_summary"]["bounding_box"] = {
                "min_x": float(valid_collar[x_column].min()),
                "max_x": float(valid_collar[x_column].max()),
                "min_y": float(valid_collar[y_column].min()),
                "max_y": float(valid_collar[y_column].max()),
                "min_z": float(valid_collar[z_column].min()),
                "max_z": float(valid_collar[z_column].max()),
            }
        except Exception as e:
            result["errors"].append(f"Failed to calculate bounding box: {e}")
            return {"status": "validation_failed", "validation": result}
        
        # Load interval files
        interval_configs = []
        for i, cfg in enumerate(interval_files):
            try:
                interval_path = Path(cfg.get('file', ''))
                if not interval_path.exists():
                    result["errors"].append(f"Interval file not found: {interval_path}")
                    continue
                
                interval_df = pd.read_csv(interval_path)
                for col in interval_df.columns:
                    if interval_df[col].dtype == 'object':
                        interval_df[col] = interval_df[col].fillna('').astype(str)
                
                req_cols = [cfg.get('id_column'), cfg.get('from_column'), cfg.get('to_column')]
                missing = [c for c in req_cols if c and c not in interval_df.columns]
                if missing:
                    result["errors"].append(f"Interval '{cfg.get('name')}' missing columns: {missing}")
                    continue
                
                attr_cols = cfg.get('attribute_columns', [])
                if not attr_cols:
                    attr_cols = [c for c in interval_df.columns if c not in set(req_cols)]
                
                interval_configs.append({
                    'name': cfg.get('name', f'collection_{i}'),
                    'dataframe': interval_df,
                    'id_col': cfg.get('id_column'),
                    'from_col': cfg.get('from_column'),
                    'to_col': cfg.get('to_column'),
                    'attribute_columns': attr_cols,
                })
                result["data_summary"][f"interval_{cfg.get('name')}_rows"] = len(interval_df)
            except Exception as e:
                result["errors"].append(f"Failed to load interval file {i}: {e}")
        
        if result["errors"]:
            return {"status": "validation_failed", "validation": result}
        
        # Dry run - just return validation results
        if dry_run:
            return {
                "status": "validation_passed",
                "message": "Dry run passed. Set dry_run=False to create the object.",
                "validation": result,
                "object_preview": {
                    "name": object_name,
                    "path": object_path,
                    "holes": unique_holes,
                    "collections": [c['name'] for c in interval_configs],
                }
            }
        
        # Create the object
        await ensure_initialized()
        
        try:
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            _cache = Cache(evo_context.cache_path)
            data_client = object_client.get_data_client(_cache)
            
            builder = DownholeCollectionBuilder(data_client)
            
            obj = builder.build(
                name=object_name,
                description=description,
                collar_df=collar_df,
                survey_df=survey_df,
                collar_id_col=collar_id_column,
                survey_id_col=survey_id_column,
                x_col=x_column,
                y_col=y_column,
                z_col=z_column,
                depth_col=depth_column,
                azimuth_col=azimuth_column,
                dip_col=dip_column,
                max_depth_col=max_depth_column,
                interval_collections=interval_configs,
                tags=tags,
                crs=coordinate_reference_system,
                invert_z=invert_z,
            )
            
            obj_dict = obj.as_dict()
            
            # Validate by reconstructing
            try:
                DownholeCollection_V1_3_0.from_dict(obj_dict)
            except Exception as e:
                return {
                    "status": "schema_validation_failed",
                    "error": str(e),
                    "validation": result,
                }
            
            await data_client.upload_referenced_data(obj_dict)
            metadata = await object_client.create_geoscience_object(object_path, obj_dict)
            
            return {
                "status": "created",
                "object_id": str(metadata.id),
                "name": metadata.name,
                "path": metadata.path,
                "version_id": metadata.version_id,
                "validation": result,
                "builder_warnings": builder.warnings,
            }
            
        except Exception as e:
            logger.exception("Failed to create object")
            return {"status": "creation_failed", "error": str(e), "validation": result}
    
    @mcp.tool()
    async def build_and_create_downhole_intervals(
        workspace_id: str,
        object_path: str,
        object_name: str,
        description: str,
        csv_file: str,
        hole_id_column: str,
        from_column: str,
        to_column: str,
        start_x_column: str,
        start_y_column: str,
        start_z_column: str,
        end_x_column: str,
        end_y_column: str,
        end_z_column: str,
        mid_x_column: str,
        mid_y_column: str,
        mid_z_column: str,
        attribute_columns: list[str] = [],
        is_composited: bool = False,
        tags: dict = {},
        coordinate_reference_system: str = "unspecified",
        dry_run: bool = True,
    ) -> dict:
        """Build and create a DownholeIntervals object from a CSV file.
        
        A DownholeIntervals object represents downhole intervals with pre-computed
        3D coordinates for start, end, and midpoint of each interval.
        Common uses: composited assay data, geological intervals with desurvey applied.
        
        Unlike DownholeCollection (which stores collar + survey data), this format
        stores the final computed coordinates for each interval directly.
        
        Args:
            workspace_id: Target Evo workspace UUID
            object_path: Path for the new object (e.g., "/intervals/assay.json")
            object_name: Display name for the object
            description: Object description
            csv_file: Path to CSV file with interval data
            hole_id_column: Hole ID column name
            from_column: From depth column name
            to_column: To depth column name
            start_x_column: Start X coordinate column
            start_y_column: Start Y coordinate column
            start_z_column: Start Z coordinate column
            end_x_column: End X coordinate column
            end_y_column: End Y coordinate column
            end_z_column: End Z coordinate column
            mid_x_column: Midpoint X coordinate column
            mid_y_column: Midpoint Y coordinate column
            mid_z_column: Midpoint Z coordinate column
            attribute_columns: Columns to include as attributes (empty = auto-detect)
            is_composited: Whether the intervals are composited (default: False)
            tags: Optional tags dictionary
            coordinate_reference_system: CRS string (default: "unspecified")
            dry_run: If True, validate only without creating (default: True)
        
        Returns:
            Dict with validation results and object info
        """
        result = {"errors": [], "warnings": [], "data_summary": {}}
        
        # Load CSV
        try:
            csv_path = Path(csv_file)
            if not csv_path.exists():
                return {"status": "error", "error": f"CSV file not found: {csv_file}"}
            df = pd.read_csv(csv_path)
            result["data_summary"]["rows"] = len(df)
            result["data_summary"]["columns"] = list(df.columns)
        except Exception as e:
            return {"status": "error", "error": f"Failed to read CSV file: {e}"}
        
        # Validate required columns
        required = [
            hole_id_column, from_column, to_column,
            start_x_column, start_y_column, start_z_column,
            end_x_column, end_y_column, end_z_column,
            mid_x_column, mid_y_column, mid_z_column,
        ]
        missing = [c for c in required if c not in df.columns]
        if missing:
            result["errors"].append(f"Missing required columns: {missing}")
            return {"status": "validation_failed", "validation": result}
        
        # Clean string columns
        for col in df.columns:
            if df[col].dtype == 'object':
                df[col] = df[col].fillna('').astype(str)
        
        # Check NaN in midpoint coordinates (used for bounding box)
        coord_cols = [mid_x_column, mid_y_column, mid_z_column]
        nan_count = df[coord_cols].isna().any(axis=1).sum()
        if nan_count > 0:
            result["warnings"].append(f"{nan_count} rows have NaN midpoint coordinates")
        if nan_count == len(df):
            result["errors"].append("All rows have NaN midpoint coordinates")
            return {"status": "validation_failed", "validation": result}
        
        # Calculate bounding box for preview
        try:
            valid_mask = df[coord_cols].notna().all(axis=1)
            valid_df = df[valid_mask]
            result["data_summary"]["bounding_box"] = {
                "min_x": float(valid_df[mid_x_column].min()),
                "max_x": float(valid_df[mid_x_column].max()),
                "min_y": float(valid_df[mid_y_column].min()),
                "max_y": float(valid_df[mid_y_column].max()),
                "min_z": float(valid_df[mid_z_column].min()),
                "max_z": float(valid_df[mid_z_column].max()),
            }
            result["data_summary"]["valid_intervals"] = len(valid_df)
        except Exception as e:
            result["errors"].append(f"Failed to calculate bounding box: {e}")
            return {"status": "validation_failed", "validation": result}
        
        # Count unique holes
        unique_holes = df[hole_id_column].nunique()
        result["data_summary"]["unique_holes"] = unique_holes
        result["data_summary"]["total_intervals"] = len(df)
        
        # Determine attribute columns
        exclude_cols = set(required)
        attr_cols = attribute_columns if attribute_columns else None
        if attr_cols is None:
            auto_attrs = [c for c in df.columns if c not in exclude_cols]
            result["data_summary"]["auto_detected_attributes"] = auto_attrs
        else:
            result["data_summary"]["specified_attributes"] = attr_cols
        
        if dry_run:
            return {
                "status": "validation_passed",
                "message": "Dry run passed. Set dry_run=False to create the object.",
                "validation": result,
                "object_preview": {
                    "name": object_name,
                    "path": object_path,
                    "intervals": result["data_summary"]["total_intervals"],
                    "holes": unique_holes,
                    "is_composited": is_composited,
                    "attributes": attr_cols or auto_attrs,
                }
            }
        
        # Create the object
        await ensure_initialized()
        
        try:
            object_client = await evo_context.get_object_client(UUID(workspace_id))
            _cache = Cache(evo_context.cache_path)
            data_client = object_client.get_data_client(_cache)
            
            builder = DownholeIntervalsBuilder(data_client)
            
            obj = builder.build(
                name=object_name,
                df=df,
                hole_id_column=hole_id_column,
                from_column=from_column,
                to_column=to_column,
                start_x_column=start_x_column,
                start_y_column=start_y_column,
                start_z_column=start_z_column,
                end_x_column=end_x_column,
                end_y_column=end_y_column,
                end_z_column=end_z_column,
                mid_x_column=mid_x_column,
                mid_y_column=mid_y_column,
                mid_z_column=mid_z_column,
                attribute_columns=attr_cols,
                is_composited=is_composited,
                description=description,
                tags=tags,
                crs=coordinate_reference_system,
            )
            
            obj_dict = obj.as_dict()
            
            # Validate by reconstructing
            try:
                DownholeIntervals_V1_3_0.from_dict(obj_dict)
            except Exception as e:
                return {
                    "status": "schema_validation_failed",
                    "error": str(e),
                    "validation": result,
                }
            
            await data_client.upload_referenced_data(obj_dict)
            metadata = await object_client.create_geoscience_object(object_path, obj_dict)
            
            return {
                "status": "created",
                "object_id": str(metadata.id),
                "name": metadata.name,
                "path": metadata.path,
                "version_id": metadata.version_id,
                "validation": result,
                "builder_warnings": builder.warnings,
            }
            
        except Exception as e:
            logger.exception("Failed to create downhole intervals")
            return {"status": "creation_failed", "error": str(e), "validation": result}
