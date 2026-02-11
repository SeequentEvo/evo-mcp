"""
Generalized object builder framework for constructing valid Geoscience Objects from CSV data.

This module provides:
1. BaseObjectBuilder - Common utilities for saving parquet data and building attributes
2. Schema registry utilities - Lookup and validate against registered schemas
3. Specialized builders for each object type:
   - PointsetBuilder - Point data with X/Y/Z coordinates and attributes
   - LineSegmentsBuilder - Line segments with vertices and segment definitions
   - DownholeCollectionBuilder - Drillhole data (in downhole_collection_builder.py)

All builders follow the same pattern:
1. Initialize with a data client for parquet storage
2. Validate input data
3. Build schema-compliant objects
4. Validate against the schema before returning
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Optional, Type, TypeVar

import pandas as pd
import numpy as np
import pyarrow as pa

from evo_schemas.components import (
    BoundingBox_V1_0_1,
    CategoryAttribute_V1_1_0,
    ContinuousAttribute_V1_1_0,
    NanCategorical_V1_0_1,
    NanContinuous_V1_0_1,
)
from evo_schemas.elements import (
    FloatArray1_V1_0_1,
    FloatArray2_V1_0_1,
    FloatArray3_V1_0_1,
    IntegerArray1_V1_0_1,
    LookupTable_V1_0_1,
)
# Import specific object types
from evo_schemas.objects.pointset import (
    Pointset_V1_3_0,
    Pointset_V1_3_0_Locations,
)
from evo_schemas.objects.line_segments import (
    LineSegments_V2_2_0,
)
from evo_schemas.components.segments import (
    Segments_V1_2_0,
    Segments_V1_2_0_Vertices,
    Segments_V1_2_0_Indices,
)
from evo_schemas.components.locations import Locations_V1_0_1
# Import downhole collection types
from evo_schemas.components import (
    CategoryData_V1_0_1,
    Intervals_V1_0_1,
    IntervalTable_V1_2_0_FromTo,
    FromTo_V1_0_1,
)
from evo_schemas.objects.downhole_collection import (
    DownholeCollection_V1_3_0,
    DownholeCollection_V1_3_0_Collections_IntervalTable,
    DownholeCollection_V1_3_0_Location,
    DownholeCollection_V1_3_0_Location_Holes,
    DownholeCollection_V1_3_0_Location_Path,
)
from evo_schemas.objects.downhole_intervals import DownholeIntervals_V1_3_0

# Set up logging
logger = logging.getLogger(__name__)


# Type variable for schema classes
T = TypeVar('T')

class BaseObjectBuilder(ABC):
    """Base class for building geoscience objects from CSV/DataFrame data.
    
    Provides common utilities for:
    - Saving data to parquet format
    - Building attributes (continuous and categorical)
    - Computing bounding boxes
    - Schema validation
    """
    
    def __init__(self, data_client):
        """Initialize with an ObjectDataClient for saving parquet data.
        
        Args:
            data_client: An ObjectDataClient instance from evo.object.utils
        """
        self.data_client = data_client
        self.errors: list[str] = []
        self.warnings: list[str] = []
        
    def _add_error(self, msg: str):
        """Log and store an error message."""
        self.errors.append(msg)
        logger.error(msg)
        
    def _add_warning(self, msg: str):
        """Log and store a warning message."""
        self.warnings.append(msg)
        logger.warning(msg)
    
    def reset_messages(self):
        """Reset errors and warnings for a new build operation."""
        self.errors = []
        self.warnings = []
    
    # =========================================================================
    # Parquet saving utilities
    # =========================================================================
    
    def save_lookup_table(self, lookup_df: pd.DataFrame) -> dict:
        """Save a lookup table to cache and return the reference dict.
        
        Args:
            lookup_df: DataFrame with 'key' (int32) and 'value' (string) columns
            
        Returns:
            Dict with parquet reference for LookupTable schema
        """
        table = pa.Table.from_pandas(
            lookup_df,
            schema=pa.schema([("key", pa.int32()), ("value", pa.string())]),
            preserve_index=False,
        )
        return self.data_client.save_table(table=table)
    
    def save_int_array(self, data: 'pd.Series') -> dict:
        """Save an integer array and return the reference dict."""
        df = pd.DataFrame({"data": data.astype('int32')})
        table = pa.Table.from_pandas(
            df,
            schema=pa.schema([("data", pa.int32())]),
            preserve_index=False,
        )
        return self.data_client.save_table(table=table)
    
    def save_float_array1(self, data: 'pd.Series') -> dict:
        """Save a 1D float array and return the reference dict."""
        df = pd.DataFrame({"data": data.astype('float64')})
        table = pa.Table.from_pandas(
            df,
            schema=pa.schema([("data", pa.float64())]),
            preserve_index=False,
        )
        return self.data_client.save_table(table=table)
    
    def save_float_array2(self, data: pd.DataFrame, col1: str, col2: str) -> dict:
        """Save a 2D float array (e.g., segment indices)."""
        arr = data[[col1, col2]].copy()
        arr.columns = ["data1", "data2"]
        table = pa.Table.from_pandas(
            arr.astype('float64'),
            schema=pa.schema([("data1", pa.float64()), ("data2", pa.float64())]),
            preserve_index=False,
        )
        return self.data_client.save_table(table=table)
    
    def save_float_array3(self, data: pd.DataFrame, col_x: str, col_y: str, col_z: str) -> dict:
        """Save a 3D float array (e.g., coordinates)."""
        arr = data[[col_x, col_y, col_z]].copy()
        arr.columns = ["x", "y", "z"]
        table = pa.Table.from_pandas(
            arr.astype('float64'),
            schema=pa.schema([("x", pa.float64()), ("y", pa.float64()), ("z", pa.float64())]),
            preserve_index=False,
        )
        return self.data_client.save_table(table=table)
    
    def save_index_array2(self, data: pd.DataFrame, col1: str, col2: str) -> dict:
        """Save a 2D index array (e.g., segment start/end indices)."""
        arr = data[[col1, col2]].copy()
        arr.columns = ["data1", "data2"]
        table = pa.Table.from_pandas(
            arr.astype('uint64'),
            schema=pa.schema([("data1", pa.uint64()), ("data2", pa.uint64())]),
            preserve_index=False,
        )
        return self.data_client.save_table(table=table)
    
    # =========================================================================
    # Attribute building utilities
    # =========================================================================
    
    def build_category_attribute(
        self, 
        data: 'pd.Series', 
        name: str
    ) -> 'CategoryAttribute_V1_1_0':
        """Build a category (string) attribute from a pandas Series."""
            
        # Clean data
        clean_data = data.fillna("").astype(str)
        
        # Create lookup table
        unique_values = clean_data.unique()
        lookup_df = pd.DataFrame({
            "key": range(1, len(unique_values) + 1),
            "value": unique_values
        })
        
        # Map values to keys
        value_to_key = dict(zip(lookup_df['value'], lookup_df['key']))
        mapped_values = clean_data.map(value_to_key).astype('int32')
        
        # Generate a unique key from the name (lowercase, no spaces)
        key = name.lower().replace(' ', '_').replace('-', '_')
        
        return CategoryAttribute_V1_1_0(
            name=name,
            key=key,
            nan_description=NanCategorical_V1_0_1(values=[]),
            table=LookupTable_V1_0_1.from_dict(self.save_lookup_table(lookup_df)),
            values=IntegerArray1_V1_0_1.from_dict(self.save_int_array(mapped_values)),
        )
    
    def build_continuous_attribute(
        self, 
        data: 'pd.Series', 
        name: str
    ) -> 'ContinuousAttribute_V1_1_0':
        """Build a continuous (float) attribute from a pandas Series."""
            
        clean_data = pd.to_numeric(data, errors='coerce').fillna(np.nan)
        
        # Generate a unique key from the name (lowercase, no spaces)
        key = name.lower().replace(' ', '_').replace('-', '_')
        
        return ContinuousAttribute_V1_1_0(
            name=name,
            key=key,
            nan_description=NanContinuous_V1_0_1(values=[]),
            values=FloatArray1_V1_0_1.from_dict(self.save_float_array1(clean_data)),
        )
    
    def build_attribute(self, data: 'pd.Series', name: str):
        """Build an attribute, automatically detecting type.
        
        Uses continuous for numeric types, categorical for strings/objects.
        """
        dtype = str(data.dtype)
        
        if dtype == 'object' or dtype.startswith('str'):
            return self.build_category_attribute(data, name)
        elif dtype in ['float64', 'float32', 'int64', 'int32', 'float', 'int']:
            return self.build_continuous_attribute(data, name)
        else:
            self._add_warning(f"Unknown dtype {dtype} for column {name}, treating as category")
            return self.build_category_attribute(data.astype(str), name)
    
    def build_attributes(
        self, 
        df: pd.DataFrame, 
        columns: list[str],
        exclude_columns: Optional[list[str]] = None
    ) -> list:
        """Build multiple attributes from DataFrame columns.
        
        Args:
            df: Source DataFrame
            columns: Columns to convert to attributes
            exclude_columns: Columns to skip (e.g., coordinate columns)
            
        Returns:
            List of attribute objects (CategoryAttribute or ContinuousAttribute)
        """
        exclude = set(exclude_columns or [])
        attributes = []
        
        for col in columns:
            if col in df.columns and col not in exclude:
                try:
                    attr = self.build_attribute(df[col], col)
                    attributes.append(attr)
                except Exception as e:
                    self._add_warning(f"Failed to build attribute '{col}': {e}")
        
        return attributes
    
    # =========================================================================
    # Bounding box utilities
    # =========================================================================
    
    def build_bounding_box(
        self, 
        df: pd.DataFrame,
        x_col: str,
        y_col: str,
        z_col: str
    ) -> 'BoundingBox_V1_0_1':
        """Build bounding box from coordinate columns.
        
        NaN values in coordinates are excluded from the calculation.
        
        Args:
            df: DataFrame with coordinate columns
            x_col, y_col, z_col: Column names for X, Y, Z coordinates
            
        Returns:
            BoundingBox_V1_0_1 object
            
        Raises:
            ValueError: If no valid coordinates found or values are invalid
        """
            
        # Filter to rows with valid (non-NaN) coordinates
        valid_mask = df[[x_col, y_col, z_col]].notna().all(axis=1)
        valid_df = df[valid_mask]
        
        if len(valid_df) == 0:
            raise ValueError("No valid coordinates found for bounding box calculation")
        
        # Calculate bounding box values (convert to Python float for JSON serialization)
        bbox_values = {
            'min_x': float(valid_df[x_col].min()),
            'max_x': float(valid_df[x_col].max()),
            'min_y': float(valid_df[y_col].min()),
            'max_y': float(valid_df[y_col].max()),
            'min_z': float(valid_df[z_col].min()),
            'max_z': float(valid_df[z_col].max()),
        }
        
        # Validate all values are finite
        for key, value in bbox_values.items():
            if not np.isfinite(value):
                raise ValueError(
                    f"Bounding box {key} is not finite: {value}. "
                    "Check coordinate data for infinite values."
                )
        
        return BoundingBox_V1_0_1(**bbox_values)
    
    # =========================================================================
    # Schema validation
    # =========================================================================
    
    def validate_object(self, obj_dict: dict, schema_class: Type[T]) -> T:
        """Validate an object dictionary against its schema.
        
        Args:
            obj_dict: Dictionary representation of the object
            schema_class: The schema class to validate against
            
        Returns:
            Reconstructed schema object (validates nested structure)
            
        Raises:
            ValueError: If validation fails
        """
        try:
            return schema_class.from_dict(obj_dict)
        except Exception as e:
            raise ValueError(f"Schema validation failed for {schema_class.__name__}: {e}")
    
    # =========================================================================
    # Abstract methods for subclasses
    # =========================================================================
    
    @abstractmethod
    def build(self, **kwargs) -> Any:
        """Build the geoscience object. Implemented by subclasses."""
        pass


class PointsetBuilder(BaseObjectBuilder):
    """Builder for Pointset objects from coordinate data with optional attributes.
    
    A Pointset is a set of points in 3D space, each with X/Y/Z coordinates
    and optional attributes (continuous or categorical).
    """
    
    def build(
        self,
        name: str,
        df: pd.DataFrame,
        x_column: str,
        y_column: str,
        z_column: str,
        attribute_columns: Optional[list[str]] = None,
        description: str = "",
        tags: Optional[dict] = None,
        crs: str = "unspecified",
    ) -> 'Pointset_V1_3_0':
        """Build a Pointset object from DataFrame data.
        
        Args:
            name: Object name
            df: DataFrame with coordinate and attribute data
            x_column, y_column, z_column: Column names for X/Y/Z coordinates
            attribute_columns: Columns to include as attributes (None = auto-detect)
            description: Object description
            tags: Optional tags dictionary
            crs: Coordinate reference system string
            
        Returns:
            Pointset_V1_3_0 object (call .as_dict() for dict form)
        """
        self.reset_messages()
        
        # Validate required columns exist
        required = [x_column, y_column, z_column]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Build coordinates
        coords_ref = self.save_float_array3(df, x_column, y_column, z_column)
        coordinates = FloatArray3_V1_0_1.from_dict(coords_ref)
        
        # Build attributes
        coord_cols = {x_column, y_column, z_column}
        if attribute_columns is None:
            # Auto-detect: all columns except coordinates
            attribute_columns = [c for c in df.columns if c not in coord_cols]
        
        attributes = self.build_attributes(df, attribute_columns, exclude_columns=list(coord_cols))
        
        # Build locations (coordinates + attributes)
        locations = Pointset_V1_3_0_Locations(
            coordinates=coordinates,
            attributes=attributes if attributes else None,
        )
        
        # Build bounding box
        bbox = self.build_bounding_box(df, x_column, y_column, z_column)
        
        return Pointset_V1_3_0(
            name=name,
            uuid=None,
            description=description,
            tags=tags or {},
            bounding_box=bbox,
            coordinate_reference_system=crs,
            locations=locations,
        )


class LineSegmentsBuilder(BaseObjectBuilder):
    """Builder for LineSegments objects from vertex and segment data.
    
    A LineSegments object consists of:
    - Vertices: 3D points (X/Y/Z coordinates) with optional attributes
    - Segments: Pairs of vertex indices defining line segments with optional attributes
    """
    
    def build(
        self,
        name: str,
        vertices_df: pd.DataFrame,
        segments_df: pd.DataFrame,
        x_column: str,
        y_column: str,
        z_column: str,
        start_index_column: str,
        end_index_column: str,
        vertex_attribute_columns: Optional[list[str]] = None,
        segment_attribute_columns: Optional[list[str]] = None,
        description: str = "",
        tags: Optional[dict] = None,
        crs: str = "unspecified",
    ) -> 'LineSegments_V2_2_0':
        """Build a LineSegments object from vertex and segment data.
        
        Args:
            name: Object name
            vertices_df: DataFrame with vertex coordinates and optional attributes
            segments_df: DataFrame with segment definitions (start/end indices) and optional attributes
            x_column, y_column, z_column: Column names for vertex X/Y/Z coordinates
            start_index_column: Column with segment start vertex indices
            end_index_column: Column with segment end vertex indices
            vertex_attribute_columns: Columns from vertices_df for attributes (None = auto-detect)
            segment_attribute_columns: Columns from segments_df for attributes (None = auto-detect)
            description: Object description
            tags: Optional tags dictionary
            crs: Coordinate reference system string
            
        Returns:
            LineSegments_V2_2_0 object (call .as_dict() for dict form)
        """
        self.reset_messages()
        
        # Validate vertices
        required_vertex_cols = [x_column, y_column, z_column]
        missing = [c for c in required_vertex_cols if c not in vertices_df.columns]
        if missing:
            raise ValueError(f"Missing required vertex columns: {missing}")
        
        # Validate segments
        required_segment_cols = [start_index_column, end_index_column]
        missing = [c for c in required_segment_cols if c not in segments_df.columns]
        if missing:
            raise ValueError(f"Missing required segment columns: {missing}")
        
        # Build vertex coordinates
        vertices_ref = self.save_float_array3(vertices_df, x_column, y_column, z_column)
        
        # Build segment indices
        indices_ref = self.save_index_array2(segments_df, start_index_column, end_index_column)
        
        # Build vertex attributes
        coord_cols = {x_column, y_column, z_column}
        if vertex_attribute_columns is None:
            vertex_attribute_columns = [c for c in vertices_df.columns if c not in coord_cols]
        vertex_attrs = self.build_attributes(
            vertices_df, vertex_attribute_columns, exclude_columns=list(coord_cols)
        )
        
        # Build segment attributes  
        index_cols = {start_index_column, end_index_column}
        if segment_attribute_columns is None:
            segment_attribute_columns = [c for c in segments_df.columns if c not in index_cols]
        segment_attrs = self.build_attributes(
            segments_df, segment_attribute_columns, exclude_columns=list(index_cols)
        )
        
        # Build Segments_V1_2_0 with embedded attributes in vertices and indices
        vertices = Segments_V1_2_0_Vertices(
            data=vertices_ref['data'],
            length=vertices_ref.get('length', len(vertices_df)),
            attributes=vertex_attrs if vertex_attrs else None,
        )
        
        indices = Segments_V1_2_0_Indices(
            data=indices_ref['data'],
            length=indices_ref.get('length', len(segments_df)),
            attributes=segment_attrs if segment_attrs else None,
        )
        
        segments = Segments_V1_2_0(
            vertices=vertices,
            indices=indices,
        )
        
        # Build bounding box from vertices
        bbox = self.build_bounding_box(vertices_df, x_column, y_column, z_column)
        
        return LineSegments_V2_2_0(
            name=name,
            uuid=None,
            description=description,
            tags=tags or {},
            bounding_box=bbox,
            coordinate_reference_system=crs,
            segments=segments,
        )


class DownholeCollectionBuilder(BaseObjectBuilder):
    """Builder for DownholeCollection objects from collar, survey, and interval data.
    
    A DownholeCollection represents drillhole data with:
    - Collar locations (X/Y/Z coordinates for each hole)
    - Survey data (depth, azimuth, dip measurements along holes)
    - Interval collections (assay, geology, or other data tied to depth intervals)
    
    Inherits common data-saving and attribute-building utilities from BaseObjectBuilder.
    """

    def build_hole_id_lookup(self, hole_ids: list[str]) -> pd.DataFrame:
        """Create a hole ID lookup table DataFrame."""
        return pd.DataFrame({
            "key": range(1, len(hole_ids) + 1),
            "value": hole_ids
        })
    
    def save_path_array(self, df: pd.DataFrame, depth_col: str, azimuth_col: str, dip_col: str) -> dict:
        """Save survey path data (distance, azimuth, dip)."""
        data = df[[depth_col, azimuth_col, dip_col]].copy()
        data.columns = ["distance", "azimuth", "dip"]
        table = pa.Table.from_pandas(
            data.astype('float64'),
            schema=pa.schema([
                ("distance", pa.float64()), 
                ("azimuth", pa.float64()), 
                ("dip", pa.float64())
            ]),
            preserve_index=False,
        )
        return self.data_client.save_table(table=table)
    
    def build_hole_index_map(self, data_df: pd.DataFrame, id_column: str, hole_id_lookup: pd.DataFrame) -> pd.DataFrame:
        """Build the hole index/offset/count mapping for interval data."""
        id_to_key = dict(zip(hole_id_lookup['value'], hole_id_lookup['key']))
        
        records = []
        current_hole = None
        current_offset = 0
        current_count = 0
        
        for idx, row in data_df.iterrows():
            hole_id = row[id_column]
            if hole_id != current_hole:
                if current_hole is not None and current_hole in id_to_key:
                    records.append({
                        'hole_index': id_to_key[current_hole],
                        'offset': current_offset,
                        'count': current_count
                    })
                current_hole = hole_id
                current_offset = idx if isinstance(idx, int) else data_df.index.get_loc(idx)
                current_count = 1
            else:
                current_count += 1
        
        # Don't forget the last hole
        if current_hole is not None and current_hole in id_to_key:
            records.append({
                'hole_index': id_to_key[current_hole],
                'offset': current_offset,
                'count': current_count
            })
        
        # Fill in missing holes with zero counts
        all_keys = set(hole_id_lookup['key'])
        existing_keys = {r['hole_index'] for r in records}
        for key in all_keys - existing_keys:
            records.append({
                'hole_index': key,
                'offset': 0,
                'count': 0
            })
        
        result = pd.DataFrame(records)
        result = result.sort_values('offset').reset_index(drop=True)
        return result
    
    def save_holes_mapping(self, holes_df: pd.DataFrame) -> dict:
        """Save the holes mapping table."""
        table = pa.Table.from_pandas(
            holes_df,
            schema=pa.schema([
                ("hole_index", pa.int32()), 
                ("offset", pa.uint64()), 
                ("count", pa.uint64())
            ]),
            preserve_index=False,
        )
        return self.data_client.save_table(table=table)
    
    def build_location(
        self,
        collar_df: pd.DataFrame,
        survey_df: pd.DataFrame,
        hole_id_lookup: pd.DataFrame,
        collar_id_col: str,
        survey_id_col: str,
        x_col: str,
        y_col: str,
        z_col: str,
        depth_col: str,
        azimuth_col: str,
        dip_col: str,        
        max_depth_col: Optional[str] = None,
    ) -> 'DownholeCollection_V1_3_0_Location':
        
        """Build the complete location structure.
        
        Args:
            collar_df: DataFrame with collar data (one row per hole)
            survey_df: DataFrame with survey data (multiple rows per hole)
            hole_id_lookup: DataFrame mapping hole IDs to integer keys
            collar_id_col: Column name in collar_df with hole IDs
            survey_id_col: Column name in survey_df with hole IDs
            x_col, y_col, z_col: Column names in collar_df for coordinates
            depth_col: Column name in survey_df for depth/distance
            azimuth_col: Column name in survey_df for azimuth
            dip_col: Column name in survey_df for dip
            max_depth_col: Column name in collar_df containing max depth values.
                          If None, max depths will be calculated from survey data.
        """
        
        # Coordinates
        coords_ref = self.save_float_array3(collar_df, x_col, y_col, z_col)
        coordinates = FloatArray3_V1_0_1.from_dict(coords_ref)
        
        # Distances (final, target, current convention)
        if max_depth_col and max_depth_col in collar_df.columns:
            # Use provided max depth column from collar data
            dist_df = collar_df[[max_depth_col, max_depth_col, max_depth_col]].copy()
            dist_df.columns = ['final', 'target', 'current']
        else:
            # Calculate max depth per hole from survey data
            max_depths = survey_df.groupby(survey_id_col)[depth_col].max().reset_index()
            max_depths.columns = [collar_id_col, '_max_depth']
            collar_with_depth = collar_df.merge(max_depths, on=collar_id_col, how='left')
            collar_with_depth['_max_depth'] = collar_with_depth['_max_depth'].fillna(0.0)
            dist_df = collar_with_depth[['_max_depth', '_max_depth', '_max_depth']].copy()
            dist_df.columns = ['final', 'target', 'current']
        
        dist_table = pa.Table.from_pandas(
            dist_df.astype('float64'),
            schema=pa.schema([("final", pa.float64()), ("target", pa.float64()), ("current", pa.float64())]),
            preserve_index=False,
        )
        distances = FloatArray3_V1_0_1.from_dict(self.data_client.save_table(table=dist_table))
        
        # Hole ID category data
        id_to_key = dict(zip(hole_id_lookup['value'], hole_id_lookup['key']))
        collar_keys = collar_df[collar_id_col].map(id_to_key).astype('int32')
        
        hole_id = CategoryData_V1_0_1(
            table=LookupTable_V1_0_1.from_dict(self.save_lookup_table(hole_id_lookup)),
            values=IntegerArray1_V1_0_1.from_dict(self.save_int_array(collar_keys)),
        )
        
        # Survey holes mapping
        survey_holes_df = self.build_hole_index_map(survey_df, survey_id_col, hole_id_lookup)
        holes = DownholeCollection_V1_3_0_Location_Holes.from_dict(
            self.save_holes_mapping(survey_holes_df)
        )
        
        # Path (survey data)
        path_ref = self.save_path_array(survey_df, depth_col, azimuth_col, dip_col)
        path = DownholeCollection_V1_3_0_Location_Path.from_dict(path_ref)
        
        return DownholeCollection_V1_3_0_Location(
            coordinates=coordinates,
            distances=distances,
            hole_id=hole_id,
            holes=holes,
            path=path,
        )
    
    def build_interval_collection(
        self,
        name: str,
        interval_df: pd.DataFrame,
        hole_id_lookup: pd.DataFrame,
        id_col: str,
        from_col: str,
        to_col: str,
        attribute_columns: list[str],
    ) -> 'DownholeCollection_V1_3_0_Collections_IntervalTable':
        """Build an interval collection (e.g., assay, geology)."""
        
        # Intervals
        intervals_ref = self.save_float_array2(interval_df, from_col, to_col)
        intervals = Intervals_V1_0_1(
            start_and_end=FloatArray2_V1_0_1.from_dict(intervals_ref)
        )
        
        # Holes mapping
        holes_df = self.build_hole_index_map(interval_df, id_col, hole_id_lookup)
        holes = DownholeCollection_V1_3_0_Location_Holes.from_dict(
            self.save_holes_mapping(holes_df)
        )
        
        # Build attributes
        exclude = {id_col, from_col, to_col}
        attributes = self.build_attributes(interval_df, attribute_columns, exclude_columns=list(exclude))
        
        return DownholeCollection_V1_3_0_Collections_IntervalTable(
            name=name,
            from_to=IntervalTable_V1_2_0_FromTo(
                intervals=intervals,
                attributes=attributes if attributes else None,
            ),
            holes=holes,
        )
    
    def build(
        self,
        name: str,
        description: str,
        collar_df: pd.DataFrame,
        survey_df: pd.DataFrame,
        collar_id_col: str,
        survey_id_col: str,
        x_col: str,
        y_col: str,
        z_col: str,
        depth_col: str,
        azimuth_col: str,
        dip_col: str,        
        max_depth_col: Optional[str] = None,
        interval_collections: Optional[list[dict]] = None,
        tags: Optional[dict] = None,
        crs: str = "unspecified",
        invert_z: bool = False,
    ) -> 'DownholeCollection_V1_3_0':
        """Build a complete DownholeCollection object.
        
        Args:
            name: Object name
            description: Object description
            collar_df: DataFrame with collar data (one row per hole)
            survey_df: DataFrame with survey data (multiple rows per hole)
            collar_id_col: Column name in collar_df with hole IDs
            survey_id_col: Column name in survey_df with hole IDs   
            x_col, y_col, z_col: Column names in collar_df for coordinates
            depth_col: Column name in survey_df for depth/distance
            azimuth_col: Column name in survey_df for azimuth
            dip_col: Column name in survey_df for dip
            max_depth_col: Column name in collar_df containing max depth values.
                          If None, max depths will be calculated from survey data.
            interval_collections: List of dicts defining interval collections to build, each with:
                - name: Collection name (e.g., "Assays")
                - dataframe: DataFrame with interval data
                - id_col: Column in dataframe with hole IDs
                - from_col: Column with from depths
                - to_col: Column with to depths
                - attribute_columns: List of columns to include as attributes (optional)
            tags: Optional tags dictionary
            crs: Coordinate reference system string
            invert_z: If True, negate dip values in the survey data. Use this when
                      drillholes appear upside down (going up instead of into the ground).
                      This handles the convention where negative dip = drilling down.
        """
        self.reset_messages()  # Reset errors and warnings from base class
        
        # Sort dataframes by hole ID
        collar_df = collar_df.sort_values(by=collar_id_col).reset_index(drop=True)
        survey_df = survey_df.sort_values(by=survey_id_col).reset_index(drop=True)
        
        # Invert dip values if requested (negative dip = drilling downward)
        if invert_z:
            survey_df = survey_df.copy()
            survey_df[dip_col] = -survey_df[dip_col]
        
        # Build hole ID lookup from collar
        unique_hole_ids = collar_df[collar_id_col].unique().tolist()
        hole_id_lookup = self.build_hole_id_lookup(unique_hole_ids)
        
        # Build bounding box
        bbox = self.build_bounding_box(collar_df, x_col, y_col, z_col)
        
        # Build location
        location = self.build_location(
            collar_df=collar_df,
            survey_df=survey_df,
            hole_id_lookup=hole_id_lookup,
            collar_id_col=collar_id_col,
            survey_id_col=survey_id_col,
            x_col=x_col,
            y_col=y_col,
            z_col=z_col,
            depth_col=depth_col,
            azimuth_col=azimuth_col,
            dip_col=dip_col,
            max_depth_col=max_depth_col,
        )
        
        # Build interval collections
        collections = []
        if interval_collections:
            for coll_config in interval_collections:
                coll_df = coll_config['dataframe'].sort_values(
                    by=[coll_config['id_col'], coll_config['from_col']]
                ).reset_index(drop=True)
                
                collection = self.build_interval_collection(
                    name=coll_config['name'],
                    interval_df=coll_df,
                    hole_id_lookup=hole_id_lookup,
                    id_col=coll_config['id_col'],
                    from_col=coll_config['from_col'],
                    to_col=coll_config['to_col'],
                    attribute_columns=coll_config.get('attribute_columns', []),
                )
                collections.append(collection)
        
        return DownholeCollection_V1_3_0(
            name=name,
            uuid=None,
            description=description,
            tags=tags or {},
            bounding_box=bbox,
            coordinate_reference_system=crs,
            location=location,
            collections=collections if collections else None,
        )


class DownholeIntervalsBuilder(BaseObjectBuilder):
    """Builder for DownholeIntervals objects from interval data with pre-computed coordinates.
    
    A DownholeIntervals object represents downhole intervals with:
    - Start, end, and midpoint 3D coordinates for each interval
    - From/to depths for each interval
    - Hole ID for each interval
    - Optional attributes on the intervals
    
    This is a "flattened" representation where each interval has its coordinates
    already computed (unlike DownholeCollection which stores collar + survey data).
    """
    
    def build(
        self,
        name: str,
        df: pd.DataFrame,
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
        attribute_columns: Optional[list[str]] = None,
        is_composited: bool = False,
        description: str = "",
        tags: Optional[dict] = None,
        crs: str = "unspecified",
    ) -> 'DownholeIntervals_V1_3_0':
        """Build a DownholeIntervals object from DataFrame data.
        
        Args:
            name: Object name
            df: DataFrame with interval data including coordinates
            hole_id_column: Column with hole IDs
            from_column: Column with from depths
            to_column: Column with to depths
            start_x_column, start_y_column, start_z_column: Start point coordinates
            end_x_column, end_y_column, end_z_column: End point coordinates
            mid_x_column, mid_y_column, mid_z_column: Midpoint coordinates
            attribute_columns: Columns to include as attributes (None = auto-detect)
            is_composited: Whether the intervals are composited
            description: Object description
            tags: Optional tags dictionary
            crs: Coordinate reference system string
            
        Returns:
            DownholeIntervals_V1_3_0 object
        """
        self.reset_messages()
        
        # Validate required columns
        required = [
            hole_id_column, from_column, to_column,
            start_x_column, start_y_column, start_z_column,
            end_x_column, end_y_column, end_z_column,
            mid_x_column, mid_y_column, mid_z_column,
        ]
        missing = [c for c in required if c not in df.columns]
        if missing:
            raise ValueError(f"Missing required columns: {missing}")
        
        # Build start locations
        start_ref = self.save_float_array3(df, start_x_column, start_y_column, start_z_column)
        start = Locations_V1_0_1(
            coordinates=FloatArray3_V1_0_1.from_dict(start_ref)
        )
        
        # Build end locations
        end_ref = self.save_float_array3(df, end_x_column, end_y_column, end_z_column)
        end = Locations_V1_0_1(
            coordinates=FloatArray3_V1_0_1.from_dict(end_ref)
        )
        
        # Build midpoint locations
        mid_ref = self.save_float_array3(df, mid_x_column, mid_y_column, mid_z_column)
        mid_points = Locations_V1_0_1(
            coordinates=FloatArray3_V1_0_1.from_dict(mid_ref)
        )
        
        # Build from-to intervals
        intervals_ref = self.save_float_array2(df, from_column, to_column)
        from_to = FromTo_V1_0_1(
            intervals=Intervals_V1_0_1(
                start_and_end=FloatArray2_V1_0_1.from_dict(intervals_ref)
            )
        )
        
        # Build hole ID category data
        clean_ids = df[hole_id_column].fillna("").astype(str)
        unique_ids = clean_ids.unique()
        lookup_df = pd.DataFrame({
            "key": range(1, len(unique_ids) + 1),
            "value": unique_ids
        })
        value_to_key = dict(zip(lookup_df['value'], lookup_df['key']))
        mapped_keys = clean_ids.map(value_to_key).astype('int32')
        
        hole_id = CategoryData_V1_0_1(
            table=LookupTable_V1_0_1.from_dict(self.save_lookup_table(lookup_df)),
            values=IntegerArray1_V1_0_1.from_dict(self.save_int_array(mapped_keys)),
        )
        
        # Build attributes
        exclude_cols = {
            hole_id_column, from_column, to_column,
            start_x_column, start_y_column, start_z_column,
            end_x_column, end_y_column, end_z_column,
            mid_x_column, mid_y_column, mid_z_column,
        }
        if attribute_columns is None:
            attribute_columns = [c for c in df.columns if c not in exclude_cols]
        
        attributes = self.build_attributes(df, attribute_columns, exclude_columns=list(exclude_cols))
        
        # Build bounding box from midpoints (or could use start/end)
        bbox = self.build_bounding_box(df, mid_x_column, mid_y_column, mid_z_column)
        
        return DownholeIntervals_V1_3_0(
            name=name,
            uuid=None,
            description=description,
            tags=tags or {},
            bounding_box=bbox,
            coordinate_reference_system=crs,
            is_composited=is_composited,
            start=start,
            end=end,
            mid_points=mid_points,
            from_to=from_to,
            hole_id=hole_id,
            attributes=attributes if attributes else None,
        )
