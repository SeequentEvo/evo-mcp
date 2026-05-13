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
from uuid import uuid4

import pandas as pd
from fastmcp import Context
from fastmcp.utilities.logging import get_logger

from evo_mcp.logging_utils import log_handled_failure, log_operation_event, result_with_operation_id

logger = get_logger(__name__)


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
        directory_path: str = "",
        ctx: Context | None = None,
    ) -> dict:
        """Get or set the local data directory configuration.

        The data directory is where local CSV/data files are stored for import.
        Can be set via EVO_LOCAL_DATA_DIR environment variable.

        Args:
            directory_path: New directory path to configure (leave empty to just check current)
        """
        operation_id = str(uuid4())
        await log_operation_event(
            ctx,
            logger,
            "Configuring local data directory",
            operation_id,
            directory_path=directory_path or None,
        )
        try:
            current_dir = _get_data_directory()

            if directory_path:
                # Validate the new directory exists
                new_path = Path(directory_path)
                if not new_path.exists():
                    await log_operation_event(
                        ctx,
                        logger,
                        "Local data directory does not exist",
                        operation_id,
                        ctx_level="warning",
                        directory_path=directory_path,
                        current_directory=str(current_dir),
                    )
                    return {
                        "error": f"Directory does not exist: {directory_path}",
                        "current_directory": str(current_dir),
                        "status": "invalid",
                    }

                # Note: We can't persist env vars, but we report what should be set
                result = {
                    "configured_directory": str(new_path),
                    "exists": new_path.exists(),
                    "is_directory": new_path.is_dir(),
                    "instruction": f"Set EVO_LOCAL_DATA_DIR={directory_path} in your .env file to persist this setting",
                    "status": "configured",
                }
                await log_operation_event(
                    ctx,
                    logger,
                    "Local data directory configuration evaluated",
                    operation_id,
                    status=result["status"],
                    configured_directory=result["configured_directory"],
                )
                return result_with_operation_id(operation_id, result)

            result = {
                "current_directory": str(current_dir),
                "exists": current_dir.exists(),
                "is_directory": current_dir.is_dir() if current_dir.exists() else False,
                "env_var": "EVO_LOCAL_DATA_DIR",
                "status": "current",
            }
            await log_operation_event(
                ctx,
                logger,
                "Local data directory status retrieved",
                operation_id,
                status=result["status"],
                current_directory=result["current_directory"],
                exists=result["exists"],
            )
            return result_with_operation_id(operation_id, result)
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to configure local data directory",
                operation_id,
                e,
                directory_path=directory_path or None,
            )
            raise

    @mcp.tool()
    async def list_local_data_files(
        file_pattern: str = "*.csv",
        recursive: bool = True,
        ctx: Context | None = None,
    ) -> dict:
        """List data files in the configured local data directory.

        Args:
            file_pattern: Glob pattern for files (default: *.csv)
            recursive: Search subdirectories (default: True)
        """
        operation_id = str(uuid4())
        await log_operation_event(
            ctx,
            logger,
            "Listing local data files",
            operation_id,
            file_pattern=file_pattern,
            recursive=recursive,
        )

        try:
            if ctx:
                await ctx.report_progress(progress=15, total=100)

            data_dir = _get_data_directory()

            if not data_dir.exists():
                await log_operation_event(
                    ctx,
                    logger,
                    "Local data directory missing",
                    operation_id,
                    ctx_level="warning",
                    data_directory=str(data_dir),
                )
                return {
                    "operation_id": operation_id,
                    "error": f"Data directory does not exist: {data_dir}",
                    "status": "directory_missing",
                }

            if recursive:
                files = list(data_dir.rglob(file_pattern))
            else:
                files = list(data_dir.glob(file_pattern))
            if ctx:
                await ctx.report_progress(progress=70, total=100)

            file_info = []
            for f in files:
                stat = f.stat()
                file_info.append(
                    {
                        "path": str(f),
                        "relative_path": str(f.relative_to(data_dir)),
                        "name": f.name,
                        "size_bytes": stat.st_size,
                        "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                    }
                )

            if ctx:
                await ctx.report_progress(progress=100, total=100)

            result = {
                "data_directory": str(data_dir),
                "pattern": file_pattern,
                "recursive": recursive,
                "file_count": len(files),
                "files": file_info,
            }
            await log_operation_event(
                ctx,
                logger,
                "Local data files listed",
                operation_id,
                data_directory=result["data_directory"],
                file_count=result["file_count"],
            )
            return result_with_operation_id(operation_id, result)
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to list local data files",
                operation_id,
                e,
                file_pattern=file_pattern,
                recursive=recursive,
            )
            raise

    # ==========================================================================
    # CSV Analysis Tools
    # ==========================================================================

    @mcp.tool()
    async def preview_csv_file(
        file_path: str,
        max_rows: int = 10,
        ctx: Context | None = None,
    ) -> dict:
        """Preview contents of a CSV file.

        Args:
            file_path: Path to CSV file (absolute or relative to data directory)
            max_rows: Maximum rows to preview
        """
        operation_id = str(uuid4())
        await log_operation_event(
            ctx,
            logger,
            "Previewing CSV file",
            operation_id,
            file_path=file_path,
            max_rows=max_rows,
        )

        # Resolve path
        file_path_obj = Path(file_path)
        if not file_path_obj.is_absolute():
            file_path_obj = _get_data_directory() / file_path_obj

        if not file_path_obj.exists():
            await log_operation_event(
                ctx,
                logger,
                "CSV file not found for preview",
                operation_id,
                ctx_level="warning",
                file_path=str(file_path_obj),
            )
            return {
                "operation_id": operation_id,
                "error": f"File not found: {file_path_obj}",
                "status": "file_missing",
            }

        try:
            if ctx:
                await ctx.report_progress(progress=10, total=100)

            df = pd.read_csv(file_path_obj)
            if ctx:
                await ctx.report_progress(progress=60, total=100)

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
                if df[col].dtype in ["float64", "float32", "int64", "int32"]:
                    col_info["min"] = float(df[col].min()) if not df[col].empty else None
                    col_info["max"] = float(df[col].max()) if not df[col].empty else None
                columns.append(col_info)

            # Sample data
            sample = df.head(max_rows).to_dict(orient="records")

            if ctx:
                await ctx.report_progress(progress=100, total=100)

            result = {
                "file_path": str(file_path_obj),
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "columns": columns,
                "sample_data": sample,
            }
            await log_operation_event(
                ctx,
                logger,
                "CSV preview completed",
                operation_id,
                file_path=result["file_path"],
                total_rows=result["total_rows"],
                total_columns=result["total_columns"],
            )
            return result_with_operation_id(operation_id, result)
        except Exception as e:
            await log_handled_failure(
                ctx,
                logger,
                "Failed to preview CSV file",
                operation_id,
                e,
                file_path=str(file_path_obj),
                max_rows=max_rows,
            )
            return result_with_operation_id(
                operation_id,
                {
                    "error": str(e),
                    "status": "parse_error",
                },
            )
