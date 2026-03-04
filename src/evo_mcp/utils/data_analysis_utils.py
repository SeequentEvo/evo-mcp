# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0


"""
Utility functions for currently only analyzing interval data from DownholeCollection and DownholeIntervals objects.

These utilities provide core analysis functions that can be used independently
or wrapped by MCP tools. Includes:
- Length-Weighted Mean calculations
- Accumulation metrics (grade * length)
- Gap analysis
- Multi-grade statistics
- Histogram generation

Supports both:
- DownholeCollection: Traditional drillhole data with collections of intervals
- DownholeIntervals: Flattened interval data with pre-computed coordinates
"""

import logging
from typing import Any, Optional, Tuple
from uuid import UUID

import numpy as np
import pandas as pd

from evo_mcp.context import evo_context, ensure_initialized

logger = logging.getLogger(__name__)


# =============================================================================
# Data Retrieval Utilities
# =============================================================================

async def _resolve_categorical_attribute(obj, attr_jmespath: str) -> pd.Series:
    """Resolve a categorical attribute by downloading its lookup table and integer keys.

    Categorical attributes in Evo objects are stored as:
    - ``table``: A LookupTable mapping integer keys to string values
    - ``values``: An IntegerArray1 of keys that index into the lookup table

    This mirrors the pattern used by ``object_builders.build_category_attribute``.

    Args:
        obj: The downloaded evo object
        attr_jmespath: JMESPath to the categorical attribute root
            (e.g. ``"collections[0].from_to.attributes[2]"``)

    Returns:
        pd.Series of resolved string values
    """
    # 1. Download the lookup table (key → value mapping)
    lookup_table = await obj.download_table(f"{attr_jmespath}.table")
    lookup_df = lookup_table.to_pandas()
    key_to_value = dict(zip(lookup_df["key"], lookup_df["value"]))

    # 2. Download the integer keys
    values_df = await obj.download_dataframe(f"{attr_jmespath}.values")
    int_keys = values_df.iloc[:, 0]

    # 3. Map keys to their string values
    return int_keys.map(key_to_value)


async def get_downhole_collection(workspace_id: str, object_id: str, version: str = "") -> tuple:
    """Helper to retrieve a DownholeCollection object and its data.
    
    Args:
        workspace_id: Workspace UUID string
        object_id: Object UUID string
        version: Optional version ID string
        
    Returns:
        Tuple of (object, object_dict)
    """
    await ensure_initialized()
    object_client = await evo_context.get_object_client(UUID(workspace_id))
    
    obj = await object_client.download_object_by_id(
        UUID(object_id),
        version=version if version else None
    )
    
    return obj, obj.as_dict()


async def download_interval_data(
    obj,
    collection_name: str,
    hole_id_jmespath: str = "location.hole_id",
) -> pd.DataFrame:
    """Download interval data from a collection as a DataFrame.
    
    Args:
        obj: The downloaded evo object
        collection_name: Name of the interval collection (e.g., 'assay')
        hole_id_jmespath: JMESPath to hole ID lookup
        
    Returns:
        DataFrame with hole_id, from, to, and attribute columns
        
    Raises:
        ValueError: If collection not found
    """
    obj_dict = obj.as_dict()
    
    # Find the collection by name
    collections = obj_dict.get('collections', [])
    target_collection = None
    collection_idx = None
    
    for idx, coll in enumerate(collections):
        if coll.get('name') == collection_name:
            target_collection = coll
            collection_idx = idx
            break
    
    if target_collection is None:
        raise ValueError(f"Collection '{collection_name}' not found. Available: {[c.get('name') for c in collections]}")
    
    # Download the from/to intervals
    intervals_jmespath = f"collections[{collection_idx}].from_to.intervals.start_and_end"
    intervals_df = await obj.download_dataframe(intervals_jmespath)
    intervals_df.columns = ['from', 'to']
    
    # Download the holes mapping to get hole indices
    holes_jmespath = f"collections[{collection_idx}].holes"
    holes_table = await obj.download_table(holes_jmespath)
    holes_df = holes_table.to_pandas()
    
    # Download the hole ID lookup
    hole_id_lookup_jmespath = "location.hole_id"
    hole_id_table = await obj.download_category_table(hole_id_lookup_jmespath)
    hole_id_df = hole_id_table.to_pandas()
    
    # Get the lookup table for hole IDs
    location_hole_id = obj_dict['location']['hole_id']
    lookup_jmespath = "location.hole_id.table"
    lookup_table = await obj.download_table(lookup_jmespath)
    lookup_df = lookup_table.to_pandas()
    key_to_hole_id = dict(zip(lookup_df['key'], lookup_df['value']))
    
    # Build hole_id column for intervals based on holes mapping
    hole_ids = []
    for _, row in holes_df.iterrows():
        hole_idx = row['hole_index']
        count = int(row['count'])
        hole_id = key_to_hole_id.get(hole_idx, f"UNKNOWN_{hole_idx}")
        hole_ids.extend([hole_id] * count)
    
    intervals_df['hole_id'] = hole_ids
    
    # Download all attributes
    from_to = target_collection.get('from_to', {})
    attributes = from_to.get('attributes', [])
    
    for attr_idx, attr in enumerate(attributes):
        attr_name = attr.get('name', f'attr_{attr_idx}')
        
        # Check if it's categorical or continuous.
        # Categorical attributes have both 'table' (lookup) and 'values' (int keys),
        # so we must check for 'table' first to avoid misclassifying them as continuous.
        if 'table' in attr:
            # Categorical attribute — resolve integer keys via lookup table
            attr_jmespath = f"collections[{collection_idx}].from_to.attributes[{attr_idx}]"
            try:
                resolved = await _resolve_categorical_attribute(obj, attr_jmespath)
                intervals_df[attr_name] = resolved.values
            except Exception as e:
                logger.warning(f"Failed to download category attribute {attr_name}: {e}")
        elif 'values' in attr:
            # Continuous attribute — raw float values
            attr_jmespath = f"collections[{collection_idx}].from_to.attributes[{attr_idx}].values"
            try:
                attr_df = await obj.download_dataframe(attr_jmespath)
                intervals_df[attr_name] = attr_df.iloc[:, 0].values
            except Exception as e:
                logger.warning(f"Failed to download attribute {attr_name}: {e}")
    
    return intervals_df


async def download_downhole_intervals_data(obj) -> pd.DataFrame:
    """Download interval data from a DownholeIntervals object as a DataFrame.
    
    Args:
        obj: The downloaded evo object (DownholeIntervals type)
        
    Returns:
        DataFrame with hole_id, from, to, and attribute columns
    """
    obj_dict = obj.as_dict()
    
    # Download the from/to intervals
    intervals_jmespath = "from_to.intervals.start_and_end"
    intervals_df = await obj.download_dataframe(intervals_jmespath)
    intervals_df.columns = ['from', 'to']
    
    # Download hole_id category data
    hole_id_jmespath = "hole_id"
    try:
        hole_id_table = await obj.download_category_table(hole_id_jmespath)
        hole_id_df = hole_id_table.to_pandas()
        intervals_df['hole_id'] = hole_id_df.iloc[:, 0].values
    except Exception as e:
        logger.warning(f"Failed to download hole_id: {e}")
        intervals_df['hole_id'] = 'UNKNOWN'
    
    # Download all attributes (at root level for DownholeIntervals)
    attributes = obj_dict.get('attributes', []) or []
    
    for attr_idx, attr in enumerate(attributes):
        attr_name = attr.get('name', f'attr_{attr_idx}')
        
        # Check if it's categorical or continuous.
        # Categorical attributes have both 'table' (lookup) and 'values' (int keys),
        # so we must check for 'table' first to avoid misclassifying them as continuous.
        if 'table' in attr:
            # Categorical attribute — resolve integer keys via lookup table
            attr_jmespath = f"attributes[{attr_idx}]"
            try:
                resolved = await _resolve_categorical_attribute(obj, attr_jmespath)
                intervals_df[attr_name] = resolved.values
            except Exception as e:
                logger.warning(f"Failed to download category attribute {attr_name}: {e}")
        elif 'values' in attr:
            # Continuous attribute — raw float values
            attr_jmespath = f"attributes[{attr_idx}].values"
            try:
                attr_df = await obj.download_dataframe(attr_jmespath)
                intervals_df[attr_name] = attr_df.iloc[:, 0].values
            except Exception as e:
                logger.warning(f"Failed to download attribute {attr_name}: {e}")
    
    return intervals_df


def get_object_type(obj_dict: dict) -> str:
    """Determine the type of downhole object from its schema.
    
    Args:
        obj_dict: Object dictionary
        
    Returns:
        'downhole-collection', 'downhole-intervals', or 'unknown'
    """
    schema = obj_dict.get('schema', '')
    if 'downhole-collection' in schema:
        return 'downhole-collection'
    elif 'downhole-intervals' in schema:
        return 'downhole-intervals'
    return 'unknown'


def get_downhole_intervals_info(obj_dict: dict) -> dict:
    """Extract attribute information from a DownholeIntervals object dict.
    
    Args:
        obj_dict: Object dictionary
        
    Returns:
        Dict with interval count and attribute information
    """
    # Get interval count from from_to
    from_to = obj_dict.get('from_to', {})
    intervals = from_to.get('intervals', {})
    start_and_end = intervals.get('start_and_end', {})
    interval_count = start_and_end.get('length', 0)
    
    # Get attributes
    attributes = obj_dict.get('attributes', []) or []
    attr_info = []
    
    for attr in attributes:
        attr_info.append({
            "name": attr.get('name'),
            "type": "continuous" if 'values' in attr else "categorical"
        })
    
    return {
        "interval_count": interval_count,
        "attributes": attr_info,
        "is_composited": obj_dict.get('is_composited', False)
    }


# =============================================================================
# Core Calculation Utilities
# =============================================================================

def calculate_interval_length(df: pd.DataFrame) -> pd.Series:
    """Calculate interval length from from/to columns.
    
    Args:
        df: DataFrame with 'from' and 'to' columns
        
    Returns:
        Series with interval lengths
    """
    return df['to'] - df['from']


def calculate_gaps(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate gaps between intervals for each hole.
    
    Args:
        df: DataFrame with hole_id, from, to columns
    
    Returns:
        DataFrame with hole_id, gap_start, gap_end, gap_length columns
    """
    gaps = []
    
    for hole_id in df['hole_id'].unique():
        hole_df = df[df['hole_id'] == hole_id].sort_values('from').reset_index(drop=True)
        
        for i in range(len(hole_df) - 1):
            current_to = hole_df.loc[i, 'to']
            next_from = hole_df.loc[i + 1, 'from']
            
            if next_from > current_to:
                gaps.append({
                    'hole_id': hole_id,
                    'gap_start': current_to,
                    'gap_end': next_from,
                    'gap_length': next_from - current_to
                })
    
    return pd.DataFrame(gaps)


# =============================================================================
# Statistics Functions
# =============================================================================

def calculate_interval_statistics(df: pd.DataFrame, grade_column: str) -> dict:
    """Calculate comprehensive interval statistics for a grade column.
    
    Computes:
    - Length-weighted mean: Sum(grade * length) / Sum(length)
    - Accumulation (grade-meters): Sum(grade * length)
    - Total length: Sum of all interval lengths
    - Simple statistics: min, max, mean, std, count
    
    Args:
        df: DataFrame with grade_column, from, to columns
        grade_column: Name of the grade/attribute column to analyze
        
    Returns:
        Dict with comprehensive statistics
        
    Raises:
        ValueError: If grade column not found or no valid data
    """
    if grade_column not in df.columns:
        raise ValueError(f"Column '{grade_column}' not found. Available: {list(df.columns)}")
    
    # Ensure grade column is numeric
    df = df.copy()
    df[grade_column] = pd.to_numeric(df[grade_column], errors='coerce')
    df['length'] = calculate_interval_length(df)
    
    # Filter out invalid data
    valid_mask = df[grade_column].notna() & df['length'].notna() & (df['length'] > 0)
    valid_df = df[valid_mask]
    
    if len(valid_df) == 0:
        raise ValueError("No valid data after filtering NaN values")
    
    # Calculate statistics
    total_length = float(valid_df['length'].sum())
    accumulation = float((valid_df[grade_column] * valid_df['length']).sum())
    length_weighted_mean = accumulation / total_length if total_length > 0 else 0
    
    return {
        "length_weighted_mean": length_weighted_mean,
        "accumulation_grade_meters": accumulation,
        "total_length": total_length,
        "simple_mean": float(valid_df[grade_column].mean()),
        "min": float(valid_df[grade_column].min()),
        "max": float(valid_df[grade_column].max()),
        "std": float(valid_df[grade_column].std()),
        "count": int(len(valid_df)),
        "null_count": int(df[grade_column].isna().sum()),
        "data_quality": {
            "total_intervals": len(df),
            "valid_intervals": len(valid_df),
            "invalid_intervals": len(df) - len(valid_df),
        }
    }


def calculate_statistics_by_hole(df: pd.DataFrame, grade_column: str) -> pd.DataFrame:
    """Calculate grade statistics grouped by hole ID.
    
    For each hole, computes:
    - Length-weighted mean
    - Accumulation (grade-meters)
    - Total sampled length
    - Min, max, mean grade
    - Sample count
    
    Args:
        df: DataFrame with hole_id, grade_column, from, to columns
        grade_column: Name of the grade/attribute column to analyze
        
    Returns:
        DataFrame with per-hole statistics
        
    Raises:
        ValueError: If grade column not found or no valid data
    """
    if grade_column not in df.columns:
        raise ValueError(f"Column '{grade_column}' not found. Available: {list(df.columns)}")
    
    # Prepare data
    df = df.copy()
    df[grade_column] = pd.to_numeric(df[grade_column], errors='coerce')
    df['length'] = calculate_interval_length(df)
    
    # Filter out invalid data
    valid_mask = df[grade_column].notna() & df['length'].notna() & (df['length'] > 0)
    valid_df = df[valid_mask].copy()
    
    if len(valid_df) == 0:
        raise ValueError("No valid data after filtering NaN values")
    
    # Calculate per-hole statistics
    valid_df['grade_length'] = valid_df[grade_column] * valid_df['length']
    
    hole_stats = valid_df.groupby('hole_id').agg({
        grade_column: ['min', 'max', 'mean', 'count'],
        'length': 'sum',
        'grade_length': 'sum'
    }).reset_index()
    
    # Flatten column names
    hole_stats.columns = ['hole_id', 'min_grade', 'max_grade', 'mean_grade', 
                          'sample_count', 'total_length', 'accumulation']
    
    # Calculate length-weighted mean
    hole_stats['length_weighted_mean'] = (
        hole_stats['accumulation'] / hole_stats['total_length']
    ).replace([np.inf, -np.inf], np.nan)
    
    return hole_stats


def analyze_gaps(df: pd.DataFrame) -> dict:
    """Analyze gaps in interval sampling for each hole.
    
    Identifies missing intervals (gaps) where the 'to' depth of one sample
    doesn't meet the 'from' depth of the next sample.
    
    Args:
        df: DataFrame with hole_id, from, to columns
        
    Returns:
        Dict with gap counts, lengths, and details
    """
    gaps_df = calculate_gaps(df)
    
    if len(gaps_df) == 0:
        return {
            "total_gap_count": 0,
            "total_gap_length": 0.0,
            "holes_with_gaps": 0,
            "holes_without_gaps": df['hole_id'].nunique(),
            "gap_statistics_by_hole": [],
            "gap_details": []
        }
    
    # Aggregate by hole
    hole_gap_stats = gaps_df.groupby('hole_id').agg({
        'gap_length': ['count', 'sum', 'min', 'max', 'mean']
    }).reset_index()
    hole_gap_stats.columns = ['hole_id', 'gap_count', 'total_gap_length', 
                               'min_gap', 'max_gap', 'mean_gap']
    
    return {
        "total_gap_count": int(gaps_df['gap_length'].count()),
        "total_gap_length": float(gaps_df['gap_length'].sum()),
        "holes_with_gaps": len(hole_gap_stats),
        "holes_without_gaps": df['hole_id'].nunique() - len(hole_gap_stats),
        "gap_statistics_by_hole": hole_gap_stats,
        "gap_details": gaps_df
    }


def calculate_categorical_statistics(
    df: pd.DataFrame,
    column: str,
    max_categories: int = 100,
) -> dict:
    """Calculate summary statistics for a categorical column.

    Computes value counts, frequency distribution, and per-hole breakdowns
    that are useful for understanding lithology codes, rock types, alteration
    categories, and similar text-based interval attributes.

    Args:
        df: DataFrame with the categorical column, plus hole_id, from, to.
        column: Name of the categorical column to analyse.
        max_categories: Cap the number of distinct values stored (default 100).

    Returns:
        Dict with:
        - unique_count: Number of distinct non-null values
        - null_count / total_count
        - value_counts: List of {value, count, fraction} sorted descending
        - by_hole: Per-hole unique-value lists (for drill-log coverage analysis)

    Raises:
        ValueError: If column not found in the DataFrame.
    """
    if column not in df.columns:
        raise ValueError(f"Column '{column}' not found. Available: {list(df.columns)}")

    series = df[column]
    total = len(series)
    null_count = int(series.isna().sum())
    non_null = series.dropna()

    # Overall value counts
    vc = non_null.value_counts()
    if len(vc) > max_categories:
        vc = vc.head(max_categories)
        truncated = True
    else:
        truncated = False

    # Calculate interval lengths for length-based summaries
    has_intervals = 'from' in df.columns and 'to' in df.columns
    if has_intervals:
        lengths = calculate_interval_length(df)
    else:
        lengths = None

    # Total length per category value
    length_by_value = {}
    if lengths is not None:
        valid_mask = series.notna() & lengths.notna() & (lengths > 0)
        for val in vc.index:
            val_mask = valid_mask & (series == val)
            length_by_value[str(val)] = float(lengths[val_mask].sum())

    value_counts = [
        {
            "value": str(val),
            "count": int(cnt),
            "fraction": round(cnt / max(len(non_null), 1), 4),
            "total_length": length_by_value.get(str(val), 0.0),
        }
        for val, cnt in vc.items()
    ]

    # Per-hole breakdown (unique values per hole)
    by_hole = []
    if 'hole_id' in df.columns:
        for hole_id, grp in df.groupby('hole_id'):
            hole_vals = grp[column].dropna().unique().tolist()
            by_hole.append({
                "hole_id": str(hole_id),
                "unique_values": [str(v) for v in hole_vals],
                "count": len(grp),
                "null_count": int(grp[column].isna().sum()),
            })

    return {
        "unique_count": int(non_null.nunique()),
        "total_count": total,
        "null_count": null_count,
        "truncated": truncated,
        "value_counts": value_counts,
        "by_hole": by_hole,
    }


def calculate_multi_grade_statistics(df: pd.DataFrame, grade_columns: list[str]) -> dict:
    """Calculate statistics for multiple grade columns at once.
    
    Useful for multi-element assay analysis.
    
    Args:
        df: DataFrame with grade columns, from, to
        grade_columns: List of grade column names to analyze
        
    Returns:
        Dict with statistics for each grade column and any errors
    """
    df = df.copy()
    df['length'] = calculate_interval_length(df)
    
    results = {}
    errors = []
    
    for grade_col in grade_columns:
        if grade_col not in df.columns:
            errors.append(f"Column '{grade_col}' not found")
            continue
        
        # Ensure grade column is numeric
        grade_data = pd.to_numeric(df[grade_col], errors='coerce')
        
        # Filter valid data
        valid_mask = grade_data.notna() & df['length'].notna() & (df['length'] > 0)
        valid_grades = grade_data[valid_mask]
        valid_lengths = df.loc[valid_mask, 'length']
        
        if len(valid_grades) == 0:
            results[grade_col] = {"error": "No valid numeric data"}
            continue
        
        total_length = float(valid_lengths.sum())
        accumulation = float((valid_grades * valid_lengths).sum())
        length_weighted_mean = accumulation / total_length if total_length > 0 else 0
        
        results[grade_col] = {
            "length_weighted_mean": length_weighted_mean,
            "accumulation": accumulation,
            "total_length": total_length,
            "simple_mean": float(valid_grades.mean()),
            "min": float(valid_grades.min()),
            "max": float(valid_grades.max()),
            "std": float(valid_grades.std()),
            "count": int(len(valid_grades)),
            "null_count": int(grade_data.isna().sum()),
        }
    
    return {
        "grade_statistics": results,
        "errors": errors if errors else None
    }


def generate_grade_histogram(df: pd.DataFrame, grade_column: str, bins: int = 20) -> dict:
    """Generate histogram data for a grade column in Plotly JSON schema format.
    
    Creates binned distribution data suitable for visualization with Plotly.
    Includes both length-weighted and sample count distributions as separate traces.
    
    Args:
        df: DataFrame with grade_column, from, to columns
        grade_column: Grade column to histogram
        bins: Number of histogram bins (default 20)
        
    Returns:
        Dict with Plotly JSON schema compliant histogram data containing:
        - data: List of traces (sample count and length-weighted)
        - layout: Chart layout configuration
        
    Raises:
        ValueError: If grade column not found or no valid data
    """
    if grade_column not in df.columns:
        raise ValueError(f"Column '{grade_column}' not found. Available: {list(df.columns)}")
    
    # Prepare data
    df = df.copy()
    df[grade_column] = pd.to_numeric(df[grade_column], errors='coerce')
    df['length'] = calculate_interval_length(df)
    
    valid_mask = df[grade_column].notna() & df['length'].notna() & (df['length'] > 0)
    valid_df = df[valid_mask]
    
    if len(valid_df) == 0:
        raise ValueError("No valid data for histogram")
    
    # Calculate histogram
    grades = valid_df[grade_column].values
    lengths = valid_df['length'].values
    
    # Sample count histogram
    counts, bin_edges = np.histogram(grades, bins=bins)
    
    # Length-weighted histogram
    length_weights, _ = np.histogram(grades, bins=bin_edges, weights=lengths)
    
    # Calculate bin centers for x-axis
    bin_centers = [(bin_edges[i] + bin_edges[i + 1]) / 2 for i in range(len(counts))]
    bin_widths = [bin_edges[i + 1] - bin_edges[i] for i in range(len(counts))]
    
    # Build Plotly JSON schema compliant output
    plotly_data = {
        "data": [
            {
                "type": "bar",
                "name": "Sample Count",
                "x": [float(x) for x in bin_centers],
                "y": [int(y) for y in counts],
                "width": [float(w) for w in bin_widths],
                "marker": {
                    "color": "rgb(55, 126, 184)",
                    "line": {
                        "color": "rgb(255, 255, 255)",
                        "width": 1
                    }
                },
                "hovertemplate": (
                    f"{grade_column}: %{{x:.3f}}<br>"
                    "Sample Count: %{y}<br>"
                    "<extra></extra>"
                ),
                "yaxis": "y"
            },
            {
                "type": "bar",
                "name": "Length-Weighted (m)",
                "x": [float(x) for x in bin_centers],
                "y": [float(y) for y in length_weights],
                "width": [float(w) for w in bin_widths],
                "marker": {
                    "color": "rgb(228, 26, 28)",
                    "line": {
                        "color": "rgb(255, 255, 255)",
                        "width": 1
                    }
                },
                "hovertemplate": (
                    f"{grade_column}: %{{x:.3f}}<br>"
                    "Total Length: %{y:.2f} m<br>"
                    "<extra></extra>"
                ),
                "yaxis": "y2",
                "visible": "legendonly"
            }
        ],
        "layout": {
            "title": {
                "text": f"{grade_column} Distribution Histogram",
                "font": {"size": 16}
            },
            "xaxis": {
                "title": {"text": grade_column},
                "showgrid": True,
                "zeroline": False
            },
            "yaxis": {
                "title": {"text": "Sample Count"},
                "showgrid": True,
                "side": "left"
            },
            "yaxis2": {
                "title": {"text": "Total Length (m)"},
                "overlaying": "y",
                "side": "right",
                "showgrid": False
            },
            "barmode": "overlay",
            "hovermode": "closest",
            "showlegend": True,
            "legend": {
                "x": 1.15,
                "y": 1,
                "xanchor": "left",
                "yanchor": "top"
            },
            "margin": {
                "l": 60,
                "r": 120,
                "t": 80,
                "b": 60
            }
        }
    }
    
    # Add metadata
    plotly_data["metadata"] = {
        "bin_count": bins,
        "total_samples": int(len(valid_df)),
        "grade_range": {
            "min": float(grades.min()),
            "max": float(grades.max()),
        },
        "bin_edges": [float(x) for x in bin_edges]
    }
    
    return plotly_data


def generate_grade_violin(
    df: pd.DataFrame, 
    grade_column: str, 
    group_by: Optional[str] = None,
    max_groups: int = 50
) -> dict:
    """Generate violin plot data for a grade column in Plotly JSON schema format.
    
    Creates violin plot visualization data suitable for Plotly. Can show:
    - Single violin for entire dataset (group_by=None)
    - Multiple violins grouped by a categorical column (e.g., hole_id)
    
    Args:
        df: DataFrame with grade_column, from, to columns
        grade_column: Grade column to visualize
        group_by: Optional column name to group by (e.g., 'hole_id')
        max_groups: Maximum number of groups to display (default 50)
        
    Returns:
        Dict with Plotly JSON schema compliant violin plot data containing:
        - data: List of violin traces
        - layout: Chart layout configuration
        - metadata: Additional statistics
        
    Raises:
        ValueError: If grade column not found or no valid data
    """
    if grade_column not in df.columns:
        raise ValueError(f"Column '{grade_column}' not found. Available: {list(df.columns)}")
    
    # Prepare data
    df = df.copy()
    df[grade_column] = pd.to_numeric(df[grade_column], errors='coerce')
    df['length'] = calculate_interval_length(df)
    
    valid_mask = df[grade_column].notna() & df['length'].notna() & (df['length'] > 0)
    valid_df = df[valid_mask]
    
    if len(valid_df) == 0:
        raise ValueError("No valid data for violin plot")
    
    # Check if grouping is requested
    if group_by:
        if group_by not in df.columns:
            raise ValueError(f"Group column '{group_by}' not found. Available: {list(df.columns)}")
        
        # Get unique groups
        unique_groups = valid_df[group_by].dropna().unique()
        if len(unique_groups) > max_groups:
            raise ValueError(
                f"Too many groups ({len(unique_groups)}). "
                f"Maximum allowed: {max_groups}. "
                f"Consider filtering data or choosing a different grouping column."
            )
        
        # Create a trace for each group
        traces = []
        for group in sorted(unique_groups, key=str):
            group_data = valid_df[valid_df[group_by] == group][grade_column].values
            
            traces.append({
                "type": "violin",
                "name": str(group),
                "y": [float(y) for y in group_data],
                "box": {
                    "visible": True
                },
                "meanline": {
                    "visible": True
                },
                "line": {
                    "color": None  # Plotly will auto-assign colors
                },
                "hovertemplate": (
                    f"{group_by}: {group}<br>"
                    f"{grade_column}: %{{y:.3f}}<br>"
                    "<extra></extra>"
                )
            })
        
        layout = {
            "title": {
                "text": f"{grade_column} Distribution by {group_by}",
                "font": {"size": 16}
            },
            "xaxis": {
                "title": {"text": group_by},
                "showgrid": False
            },
            "yaxis": {
                "title": {"text": grade_column},
                "showgrid": True,
                "zeroline": False
            },
            "violinmode": "group",
            "showlegend": True,
            "hovermode": "closest",
            "margin": {
                "l": 60,
                "r": 60,
                "t": 80,
                "b": 100
            }
        }
        
        metadata = {
            "group_by": group_by,
            "group_count": len(unique_groups),
            "groups": [str(g) for g in sorted(unique_groups, key=str)],
            "total_samples": int(len(valid_df)),
            "grade_range": {
                "min": float(valid_df[grade_column].min()),
                "max": float(valid_df[grade_column].max())
            }
        }
        
    else:
        # Single violin for entire dataset
        grades = valid_df[grade_column].values
        
        traces = [{
            "type": "violin",
            "name": grade_column,
            "y": [float(y) for y in grades],
            "box": {
                "visible": True
            },
            "meanline": {
                "visible": True
            },
            "fillcolor": "rgb(55, 126, 184)",
            "line": {
                "color": "rgb(55, 126, 184)"
            },
            "hovertemplate": (
                f"{grade_column}: %{{y:.3f}}<br>"
                "<extra></extra>"
            )
        }]
        
        layout = {
            "title": {
                "text": f"{grade_column} Distribution",
                "font": {"size": 16}
            },
            "yaxis": {
                "title": {"text": grade_column},
                "showgrid": True,
                "zeroline": False
            },
            "showlegend": False,
            "hovermode": "closest",
            "margin": {
                "l": 60,
                "r": 60,
                "t": 80,
                "b": 60
            }
        }
        
        metadata = {
            "group_by": None,
            "total_samples": int(len(valid_df)),
            "grade_range": {
                "min": float(grades.min()),
                "max": float(grades.max())
            },
            "statistics": {
                "mean": float(grades.mean()),
                "median": float(np.median(grades)),
                "std": float(grades.std()),
                "q1": float(np.percentile(grades, 25)),
                "q3": float(np.percentile(grades, 75))
            }
        }
    
    return {
        "data": traces,
        "layout": layout,
        "metadata": metadata
    }


def get_collection_info(obj_dict: dict) -> list[dict]:
    """Extract collection information from a DownholeCollection object dict.
    
    For DownholeCollection: Returns list of collections with their attributes.
    For DownholeIntervals: Returns a single pseudo-collection representing the intervals.
    
    Args:
        obj_dict: Object dictionary
        
    Returns:
        List of collection info dicts with name, type, and attributes
    """
    object_type = get_object_type(obj_dict)
    
    # Handle DownholeIntervals - create a pseudo-collection
    if object_type == 'downhole-intervals':
        attributes = obj_dict.get('attributes', []) or []
        attr_info = []
        for attr in attributes:
            attr_info.append({
                "name": attr.get('name'),
                "type": "continuous" if 'values' in attr else "categorical"
            })
        
        return [{
            "name": "intervals",  # Pseudo-collection name for DownholeIntervals
            "type": "downhole_intervals",
            "attributes": attr_info
        }]
    
    # Handle DownholeCollection
    collections = obj_dict.get('collections', [])
    result = []
    
    for coll in collections:
        coll_info = {
            "name": coll.get('name'),
            "type": "interval_table" if 'from_to' in coll else "unknown",
        }
        
        # Get attribute info
        from_to = coll.get('from_to', {})
        attributes = from_to.get('attributes', [])
        coll_info['attributes'] = []
        
        for attr in attributes:
            attr_info = {
                "name": attr.get('name'),
                "type": "continuous" if 'values' in attr else "categorical"
            }
            coll_info['attributes'].append(attr_info)
        
        result.append(coll_info)
    
    return result
