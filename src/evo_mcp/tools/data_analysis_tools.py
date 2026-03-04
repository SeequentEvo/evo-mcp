# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0


import logging
from typing import Any, Optional
from uuid import UUID

import numpy as np
import pandas as pd

from evo_mcp.utils import (
    get_downhole_collection,
    download_interval_data,
    download_downhole_intervals_data,
    get_object_type,
    calculate_interval_statistics,
    calculate_statistics_by_hole,
    analyze_gaps,
    calculate_multi_grade_statistics,
    generate_grade_histogram,
    generate_grade_violin,
    get_collection_info,
)

logger = logging.getLogger(__name__)


async def _get_interval_dataframe(obj, obj_dict: dict, collection_name: str) -> pd.DataFrame:
    """Helper to get interval DataFrame from either object type.
    
    Args:
        obj: The downloaded evo object
        obj_dict: Object dictionary
        collection_name: Collection name (use 'intervals' for DownholeIntervals)
        
    Returns:
        DataFrame with hole_id, from, to, and attribute columns
    """
    object_type = get_object_type(obj_dict)
    
    if object_type == 'downhole-intervals':
        return await download_downhole_intervals_data(obj)
    else:
        return await download_interval_data(obj, collection_name)


def register_data_analysis_tools(mcp):
    """Register data analysis tools for DownholeCollection and DownholeIntervals objects."""

    @mcp.tool()
    async def list_downhole_collections(
        workspace_id: str,
        object_id: str,
        version: str = ""
    ) -> dict:
        """List all interval collections in a DownholeCollection object.
        
        Use this to discover available collections before running analysis.
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeCollection object UUID
            version: Specific version ID (optional)
            
        Returns:
            Dict with collection names and their attribute information
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        # Check this is a downhole collection
        object_type = get_object_type(obj_dict)
        if object_type != 'downhole-collection':
            schema_id = obj.metadata.schema_id.sub_classification
            return {
                "status": "error",
                "error": f"Object is not a DownholeCollection. Schema: {schema_id}. Use list_downhole_intervals_attributes for DownholeIntervals."
            }
        
        collections = get_collection_info(obj_dict)
        
        # Get hole count
        hole_count = 0
        location = obj_dict.get('location', {})
        if 'coordinates' in location:
            hole_count = location['coordinates'].get('length', 0)
        
        return {
            "status": "success",
            "object_name": obj_dict.get('name'),
            "object_type": object_type,
            "hole_count": hole_count,
            "collection_count": len(collections),
            "collections": collections
        }

    @mcp.tool()
    async def list_downhole_intervals_attributes(
        workspace_id: str,
        object_id: str,
        version: str = ""
    ) -> dict:
        """List attributes available in a DownholeIntervals object.
        
        Use this to discover available attributes before running analysis.
        DownholeIntervals objects have a flat structure with attributes directly
        on the intervals (no named collections like DownholeCollection).
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeIntervals object UUID
            version: Specific version ID (optional)
            
        Returns:
            Dict with interval count and attribute information
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        # Check this is a downhole intervals object
        object_type = get_object_type(obj_dict)
        if object_type != 'downhole-intervals':
            schema_id = obj.metadata.schema_id.sub_classification
            return {
                "status": "error",
                "error": f"Object is not a DownholeIntervals. Schema: {schema_id}. Use list_downhole_collections for DownholeCollection."
            }
        
        # Get interval count from from_to
        from_to = obj_dict.get('from_to', {})
        intervals = from_to.get('intervals', {})
        start_and_end = intervals.get('start_and_end', {})
        interval_count = start_and_end.get('length', 0)
        
        # Get unique hole count from hole_id lookup table
        hole_id = obj_dict.get('hole_id', {})
        hole_table = hole_id.get('table', {})
        unique_hole_count = hole_table.get('length', 0)
        
        # Get attributes
        attributes = obj_dict.get('attributes', []) or []
        attr_info = []
        for attr in attributes:
            attr_info.append({
                "name": attr.get('name'),
                "type": "continuous" if 'values' in attr else "categorical"
            })
        
        return {
            "status": "success",
            "object_name": obj_dict.get('name'),
            "object_type": object_type,
            "interval_count": interval_count,
            "unique_hole_count": unique_hole_count,
            "is_composited": obj_dict.get('is_composited', False),
            "attribute_count": len(attr_info),
            "attributes": attr_info
        }

    @mcp.tool()
    async def get_interval_statistics(
        workspace_id: str,
        object_id: str,
        collection_name: str,
        grade_column: str,
        version: str = ""
    ) -> dict:
        """Calculate comprehensive interval statistics for a grade column.
        
        Computes:
        - Length-weighted mean: Sum(grade * length) / Sum(length)
        - Accumulation (grade-meters): Sum(grade * length)
        - Total length: Sum of all interval lengths
        - Simple statistics: min, max, mean, std, count
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeCollection or DownholeIntervals object UUID
            collection_name: Name of the interval collection (use 'intervals' for DownholeIntervals)
            grade_column: Name of the grade/attribute column to analyze
            version: Specific version ID (optional)
            
        Returns:
            Dict with comprehensive statistics
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
            df = await _get_interval_dataframe(obj, obj_dict, collection_name)
            stats = calculate_interval_statistics(df, grade_column)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        return {
            "status": "success",
            "collection_name": collection_name,
            "grade_column": grade_column,
            "statistics": {
                "length_weighted_mean": stats["length_weighted_mean"],
                "accumulation_grade_meters": stats["accumulation_grade_meters"],
                "total_length": stats["total_length"],
                "simple_mean": stats["simple_mean"],
                "min": stats["min"],
                "max": stats["max"],
                "std": stats["std"],
                "count": stats["count"],
                "null_count": stats["null_count"],
            },
            "data_quality": stats["data_quality"]
        }

    @mcp.tool()
    async def get_statistics_by_hole(
        workspace_id: str,
        object_id: str,
        collection_name: str,
        grade_column: str,
        version: str = ""
    ) -> dict:
        """Calculate grade statistics grouped by hole ID.
        
        For each hole, computes:
        - Length-weighted mean
        - Accumulation (grade-meters)
        - Total sampled length
        - Min, max, mean grade
        - Sample count
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeCollection or DownholeIntervals object UUID
            collection_name: Name of the interval collection (use 'intervals' for DownholeIntervals)
            grade_column: Name of the grade/attribute column to analyze
            version: Specific version ID (optional)
            
        Returns:
            Dict with per-hole statistics
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
            df = await _get_interval_dataframe(obj, obj_dict, collection_name)
            hole_stats = calculate_statistics_by_hole(df, grade_column)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        # Convert to records
        records = hole_stats.to_dict(orient='records')
        
        # Round floats for cleaner output
        for record in records:
            for key in ['min_grade', 'max_grade', 'mean_grade', 'length_weighted_mean', 
                        'total_length', 'accumulation']:
                if key in record and record[key] is not None:
                    record[key] = round(float(record[key]), 6)
            record['sample_count'] = int(record['sample_count'])
        
        return {
            "status": "success",
            "collection_name": collection_name,
            "grade_column": grade_column,
            "hole_count": len(records),
            "hole_statistics": records,
            "summary": {
                "best_hole_by_lwm": max(records, key=lambda x: x['length_weighted_mean'] or 0)['hole_id'],
                "best_hole_by_max": max(records, key=lambda x: x['max_grade'] or 0)['hole_id'],
                "most_sampled_hole": max(records, key=lambda x: x['total_length'])['hole_id'],
            }
        }

    @mcp.tool()
    async def get_gap_analysis(
        workspace_id: str,
        object_id: str,
        collection_name: str,
        version: str = ""
    ) -> dict:
        """Analyze gaps in interval sampling for each hole.
        
        Identifies missing intervals (gaps) where the 'to' depth of one sample
        doesn't meet the 'from' depth of the next sample.
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeCollection or DownholeIntervals object UUID
            collection_name: Name of the interval collection (use 'intervals' for DownholeIntervals)
            version: Specific version ID (optional)
            
        Returns:
            Dict with gap counts and lengths by hole
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
            df = await _get_interval_dataframe(obj, obj_dict, collection_name)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        # Analyze gaps
        gap_analysis = analyze_gaps(df)
        
        if gap_analysis["total_gap_count"] == 0:
            return {
                "status": "success",
                "collection_name": collection_name,
                "message": "No gaps found - intervals are contiguous",
                "total_gap_count": 0,
                "total_gap_length": 0.0,
                "holes_with_gaps": 0,
                "holes_without_gaps": gap_analysis["holes_without_gaps"],
                "gap_details": []
            }
        
        # Get DataFrames from analysis
        hole_gap_stats = gap_analysis["gap_statistics_by_hole"]
        gaps_df = gap_analysis["gap_details"]
        
        # Round floats
        for col in ['total_gap_length', 'min_gap', 'max_gap', 'mean_gap']:
            if col in hole_gap_stats.columns:
                hole_gap_stats[col] = hole_gap_stats[col].round(4)
        hole_gap_stats['gap_count'] = hole_gap_stats['gap_count'].astype(int)
        
        hole_records = hole_gap_stats.to_dict(orient='records')
        
        # Detailed gaps (limit to first 100)
        gap_details = gaps_df.head(100).to_dict(orient='records')
        for gap in gap_details:
            gap['gap_length'] = round(gap['gap_length'], 4)
            gap['gap_start'] = round(gap['gap_start'], 4)
            gap['gap_end'] = round(gap['gap_end'], 4)
        
        return {
            "status": "success",
            "collection_name": collection_name,
            "total_gap_count": gap_analysis["total_gap_count"],
            "total_gap_length": round(gap_analysis["total_gap_length"], 4),
            "holes_with_gaps": gap_analysis["holes_with_gaps"],
            "holes_without_gaps": gap_analysis["holes_without_gaps"],
            "gap_statistics_by_hole": hole_records,
            "gap_details": gap_details,
            "gap_details_truncated": len(gaps_df) > 100
        }

    @mcp.tool()
    async def get_interval_data_preview(
        workspace_id: str,
        object_id: str,
        collection_name: str,
        max_rows: int = 50,
        version: str = ""
    ) -> dict:
        """Preview interval data from a collection.
        
        Downloads and returns a sample of the interval data with all attributes.
        Useful for understanding the data structure before running analysis.
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeCollection or DownholeIntervals object UUID
            collection_name: Name of the interval collection (use 'intervals' for DownholeIntervals)
            max_rows: Maximum rows to return (default 50)
            version: Specific version ID (optional)
            
        Returns:
            Dict with data preview and column information
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
            df = await _get_interval_dataframe(obj, obj_dict, collection_name)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        # Calculate interval lengths
        from evo_mcp.utils import calculate_interval_length
        df['interval_length'] = calculate_interval_length(df)
        
        # Column info
        columns = []
        for col in df.columns:
            col_info = {
                "name": col,
                "dtype": str(df[col].dtype),
                "non_null_count": int(df[col].count()),
                "null_count": int(df[col].isnull().sum()),
            }
            if df[col].dtype in ['float64', 'float32', 'int64', 'int32']:
                col_info["min"] = float(df[col].min()) if not df[col].empty else None
                col_info["max"] = float(df[col].max()) if not df[col].empty else None
            elif df[col].dtype == 'object':
                col_info["unique_count"] = int(df[col].nunique())
            columns.append(col_info)
        
        # Sample data
        sample = df.head(max_rows).to_dict(orient='records')
        
        return {
            "status": "success",
            "collection_name": collection_name,
            "total_rows": len(df),
            "unique_holes": int(df['hole_id'].nunique()),
            "columns": columns,
            "sample_rows": len(sample),
            "sample_data": sample
        }

    @mcp.tool()
    async def get_multi_grade_statistics(
        workspace_id: str,
        object_id: str,
        collection_name: str,
        grade_columns: list[str],
        version: str = ""
    ) -> dict:
        """Calculate statistics for multiple grade columns at once.
        
        Useful for multi-element assay analysis where you need stats for
        multiple elements (Au, Cu, Ag, etc.) in a single call.
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeCollection or DownholeIntervals object UUID
            collection_name: Name of the interval collection (use 'intervals' for DownholeIntervals)
            grade_columns: List of grade column names to analyze
            version: Specific version ID (optional)
            
        Returns:
            Dict with statistics for each grade column
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
            df = await _get_interval_dataframe(obj, obj_dict, collection_name)
            result = calculate_multi_grade_statistics(df, grade_columns)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        # Round the statistics
        for grade_col, stats in result["grade_statistics"].items():
            if isinstance(stats, dict) and "error" not in stats:
                for key in ['length_weighted_mean', 'accumulation', 'total_length', 'simple_mean', 'min', 'max', 'std']:
                    if key in stats:
                        stats[key] = round(stats[key], 6)
        
        return {
            "status": "success" if not result["errors"] else "partial",
            "collection_name": collection_name,
            "grade_statistics": result["grade_statistics"],
            "errors": result["errors"],
            "available_columns": list(df.columns)
        }

    @mcp.tool()
    async def get_grade_histogram(
        workspace_id: str,
        object_id: str,
        collection_name: str,
        grade_column: str,
        bins: int = 20,
        version: str = ""
    ) -> dict:
        """Generate Plotly-compatible histogram data for a grade column.
        
        Creates histogram visualization data in Plotly JSON schema format with:
        - Sample count distribution (primary y-axis)
        - Length-weighted distribution (secondary y-axis)
        
        The output can be directly used with Plotly visualization libraries.
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeCollection or DownholeIntervals object UUID
            collection_name: Name of the interval collection (use 'intervals' for DownholeIntervals)
            grade_column: Grade column to histogram
            bins: Number of histogram bins (default 20)
            version: Specific version ID (optional)
            
        Returns:
            Dict with Plotly JSON schema compliant histogram data including:
            - data: List of histogram traces
            - layout: Chart layout configuration
            - metadata: Additional histogram statistics
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
            df = await _get_interval_dataframe(obj, obj_dict, collection_name)
            plotly_data = generate_grade_histogram(df, grade_column, bins)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        return {
            "status": "success",
            "collection_name": collection_name,
            "grade_column": grade_column,
            "plotly": plotly_data
        }

    @mcp.tool()
    async def get_grade_violin(
        workspace_id: str,
        object_id: str,
        collection_name: str,
        grade_column: str,
        group_by: str = "",
        max_groups: int = 50,
        version: str = ""
    ) -> dict:
        """Generate Plotly-compatible violin plot data for a grade column.
        
        Creates violin plot visualization data in Plotly JSON schema format showing
        the distribution of grade values. Can display:
        - Single violin for entire dataset (when group_by is empty)
        - Multiple violins grouped by a categorical column (e.g., hole_id, rock_type)
        
        Violin plots show the full distribution shape with quartiles and mean,
        making them ideal for comparing grade distributions across holes or zones.
        
        Args:
            workspace_id: Workspace UUID
            object_id: DownholeCollection or DownholeIntervals object UUID
            collection_name: Name of the interval collection (use 'intervals' for DownholeIntervals)
            grade_column: Grade column to visualize
            group_by: Optional column name to group by (e.g., 'hole_id'). Empty string for no grouping.
            max_groups: Maximum number of groups to display (default 50)
            version: Specific version ID (optional)
            
        Returns:
            Dict with Plotly JSON schema compliant violin plot data including:
            - data: List of violin traces
            - layout: Chart layout configuration
            - metadata: Group information and statistics
        """
        try:
            obj, obj_dict = await get_downhole_collection(workspace_id, object_id, version)
            df = await _get_interval_dataframe(obj, obj_dict, collection_name)
            
            # Empty string means no grouping (None)
            group_by_val = group_by if group_by else None
            
            plotly_data = generate_grade_violin(df, grade_column, group_by_val, max_groups)
        except Exception as e:
            return {"status": "error", "error": str(e)}
        
        return {
            "status": "success",
            "collection_name": collection_name,
            "grade_column": grade_column,
            "group_by": group_by if group_by else None,
            "plotly": plotly_data
        }
