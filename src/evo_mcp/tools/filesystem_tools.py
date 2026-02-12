# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
MCP tools for local file system data connector operations.

These tools manage a configured local data directory and enable:
- Listing data files in the local directory
- Previewing CSV file contents and structure

Configuration:
- Set EVO_LOCAL_DATA_DIR environment variable to specify the data directory
"""

import os
from datetime import datetime
from pathlib import Path
import pandas as pd


def _get_data_directory() -> Path:
    """Get the configured local data directory from environment."""
    data_dir = os.getenv("EVO_LOCAL_DATA_DIR", "")
    if not data_dir:
        # Fall back to a default relative to the repo
        repo_root = Path(__file__).parent.parent.parent.parent
        data_dir = repo_root / "data"
    return Path(data_dir).expanduser()


def register_filesystem_tools(mcp):
    """Register local file system connector tools with the FastMCP server."""

    # ==========================================================================
    # Configuration and Discovery Tools
    # ==========================================================================

    @mcp.tool()
    async def configure_local_data_directory(
        directory_path: str = ""
    ) -> dict:
        """Get or set the local data directory configuration.
        
        The data directory is where local CSV/data files are stored for import.
        Can be set via EVO_LOCAL_DATA_DIR environment variable.
        
        Args:
            directory_path: New directory path to configure (leave empty to just check current)
        """
        current_dir = _get_data_directory()
        
        if directory_path:
            # Validate the new directory exists
            new_path = Path(directory_path)
            if not new_path.exists():
                return {
                    "error": f"Directory does not exist: {directory_path}",
                    "current_directory": str(current_dir),
                    "status": "invalid"
                }
            
            # Note: We can't persist env vars, but we report what should be set
            return {
                "configured_directory": str(new_path),
                "exists": new_path.exists(),
                "is_directory": new_path.is_dir(),
                "instruction": f"Set EVO_LOCAL_DATA_DIR={directory_path} in your .env file to persist this setting",
                "status": "configured"
            }
        
        return {
            "current_directory": str(current_dir),
            "exists": current_dir.exists(),
            "is_directory": current_dir.is_dir() if current_dir.exists() else False,
            "env_var": "EVO_LOCAL_DATA_DIR",
            "status": "current"
        }

    @mcp.tool()
    async def list_local_data_files(
        file_pattern: str = "*.csv",
        recursive: bool = True
    ) -> dict:
        """List data files in the configured local data directory.
        
        Args:
            file_pattern: Glob pattern for files (default: *.csv)
            recursive: Search subdirectories (default: True)
        """
        data_dir = _get_data_directory()
        
        if not data_dir.exists():
            return {
                "error": f"Data directory does not exist: {data_dir}",
                "status": "directory_missing"
            }
        
        if recursive:
            files = list(data_dir.rglob(file_pattern))
        else:
            files = list(data_dir.glob(file_pattern))
        
        file_info = []
        for f in files:
            stat = f.stat()
            file_info.append({
                "path": str(f),
                "relative_path": str(f.relative_to(data_dir)),
                "name": f.name,
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        
        return {
            "data_directory": str(data_dir),
            "pattern": file_pattern,
            "recursive": recursive,
            "file_count": len(files),
            "files": file_info,
        }

    # ==========================================================================
    # CSV Analysis Tools
    # ==========================================================================

    @mcp.tool()
    async def preview_csv_file(
        file_path: str,
        max_rows: int = 10
    ) -> dict:
        """Preview contents of a CSV file.
        
        Args:
            file_path: Path to CSV file (absolute or relative to data directory)
            max_rows: Maximum rows to preview
        """
        
        # Resolve path
        file_path = Path(file_path)
        if not file_path.is_absolute():
            file_path = _get_data_directory() / file_path
        
        if not file_path.exists():
            return {
                "error": f"File not found: {file_path}",
                "status": "file_missing"
            }
        
        try:
            df = pd.read_csv(file_path)
            
            # Get column info
            columns = []
            for col in df.columns:
                col_info = {
                    "name": col,
                    "dtype": str(df[col].dtype),
                    "non_null_count": int(df[col].count()),
                    "null_count": int(df[col].isnull().sum()),
                    "unique_count": int(df[col].nunique()),
                }
                if df[col].dtype in ['float64', 'float32', 'int64', 'int32']:
                    col_info["min"] = float(df[col].min()) if not df[col].empty else None
                    col_info["max"] = float(df[col].max()) if not df[col].empty else None
                columns.append(col_info)
            
            # Sample data
            sample = df.head(max_rows).to_dict(orient='records')
            
            return {
                "file_path": str(file_path),
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "columns": columns,
                "sample_data": sample,
            }
        except Exception as e:
            return {
                "error": str(e),
                "status": "parse_error"
            }
