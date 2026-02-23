"""
MCP tools for file operations in Evo workspaces.

These tools enable uploading, downloading, and managing files in Evo workspaces:
- upload_file: Upload local files to a workspace
- download_file: Download workspace files to the configured local data directory
- list_file_versions: List all versions of a file in a workspace
- list_files: List all files in a workspace

Configuration:
- Set EVO_LOCAL_DATA_DIR environment variable for download destination
"""

import logging
import os
from pathlib import Path
from uuid import UUID

from evo_mcp.context import evo_context, ensure_initialized

logger = logging.getLogger(__name__)
from evo_mcp.tools.filesystem_tools import _get_data_directory


def register_file_tools(mcp):
    """Register file-related tools with the FastMCP server."""

    @mcp.tool()
    async def upload_file(
        workspace_id: str,
        local_file_path: str,
        target_path: str = ""
    ) -> dict:
        """Upload a local file to a workspace.
        
        Args:
            workspace_id: Workspace UUID to upload to
            local_file_path: Path to the local file to upload
            target_path: Target folder path in workspace (optional, defaults to root folder)
            
        Returns:
            File metadata including id, path, and version
        """
        await ensure_initialized()
        
        local_path = Path(local_file_path)
        if not local_path.exists():
            return {
                "error": f"Local file not found: {local_file_path}",
                "status": "file_not_found"
            }
        
        # Build target path: folder + filename
        if not target_path:
            # Default to root folder
            full_target_path = f"/{local_path.name}"
        else:
            # Ensure target_path starts with /
            if not target_path.startswith("/"):
                target_path = f"/{target_path}"
            # Append filename to target folder path
            full_target_path = f"{target_path}/{local_path.name}"
        
        try:
            file_client = await evo_context.get_file_client(UUID(workspace_id))
            
            # Prepare upload context
            upload_ctx = await file_client.prepare_upload_by_path(full_target_path)
            
            # Upload the file
            await upload_ctx.upload_from_path(str(local_path), evo_context.connector.transport)
            
            return {
                "status": "uploaded",
                "file_id": str(upload_ctx.file_id),
                "path": full_target_path,
                "version_id": upload_ctx.version_id,
                "local_file": str(local_path),
            }
        except Exception as e:
            logger.exception("Failed to upload file")
            return {"status": "upload_failed", "error": str(e), "path": full_target_path}

    @mcp.tool()
    async def list_file_versions(
        workspace_id: str,
        file_path: str
    ) -> dict:
        """List all versions of a file in a workspace.
        
        Args:
            workspace_id: Workspace UUID
            file_path: Path to the file in workspace (e.g., "/Core Logging_Headers.csv")
            
        Returns:
            List of file versions with version_id and created_at
        """
        await ensure_initialized()
        
        # Ensure file_path starts with /
        if not file_path.startswith("/"):
            file_path = f"/{file_path}"
        
        file_client = await evo_context.get_file_client(UUID(workspace_id))
        
        versions = await file_client.list_versions_by_path(file_path)
        
        versions_list = [
            {
                "version_id": v.version_id,
                "created_at": v.created_at.isoformat() if v.created_at else None,
            }
            for v in versions
        ]
        
        return {
            "file_path": file_path,
            "total_versions": len(versions_list),
            "versions": versions_list,
        }

    @mcp.tool()
    async def download_file(
        workspace_id: str,
        file_path: str,
        local_filename: str = "",
        version: str = ""
    ) -> dict:
        """Download a file from a workspace to the local data directory.
        
        Args:
            workspace_id: Workspace UUID
            file_path: Path to the file in workspace (e.g., "/data/myfile.csv")
            local_filename: Optional custom filename for downloaded file (defaults to original name)
            version: Specific version ID to download (optional, defaults to latest)
            
        Returns:
            Download status with local file path
        """
        await ensure_initialized()
        
        # Get local data directory (falls back to directory's data folder if EVO_LOCAL_DATA_DIR not set)
        data_dir = _get_data_directory()
        
        if not data_dir.exists():
            return {
                "error": f"Local data directory does not exist: {data_dir}",
                "status": "directory_missing",
                "hint": "Create the directory or set EVO_LOCAL_DATA_DIR environment variable to a valid path"
            }
        
        # Ensure file_path starts with /
        if not file_path.startswith("/"):
            file_path = f"/{file_path}"
        
        # Determine local filename
        if not local_filename:
            local_filename = Path(file_path).name
        
        local_file_path = data_dir / local_filename
        
        file_client = await evo_context.get_file_client(UUID(workspace_id))
        
        try:
            # Prepare download context
            if version:
                # Download specific version by file ID
                download_ctx = await file_client.prepare_download_by_path(file_path,version_id=version)
            else:
                download_ctx = await file_client.prepare_download_by_path(file_path)
            
            # Download the file to local path
            await download_ctx.download_to_path(str(local_file_path), evo_context.connector.transport)
            
            return {
                "file_path": file_path,
                "local_file": str(local_file_path),
                "version_id": download_ctx.version_id if hasattr(download_ctx, 'version_id') else version,
                "size_bytes": local_file_path.stat().st_size if local_file_path.exists() else None,
                "status": "downloaded"
            }
        except Exception as e:
            return {
                "error": str(e),
                "file_path": file_path,
                "status": "download_failed"
            }

    @mcp.tool()
    async def list_files(
        workspace_id: str,
        path_filter: str = ""
    ) -> dict:
        """List all files in a workspace.
        
        Args:
            workspace_id: Workspace UUID
            path_filter: Optional path prefix to filter files (e.g., "/data" to list files in /data folder)
            
        Returns:
            List of files with id, name, and path
        """
        await ensure_initialized()
        
        file_client = await evo_context.get_file_client(UUID(workspace_id))
        
        all_files = await file_client.list_all_files()
        
        # Apply path filter if provided
        if path_filter:
            if not path_filter.startswith("/"):
                path_filter = f"/{path_filter}"
            all_files = [f for f in all_files if f.path.startswith(path_filter)]
        
        files_list = [
            {
                "id": str(file.id),
                "name": file.name,
                "path": file.path
            }
            for file in all_files
        ]
        
        return {
            "workspace_id": workspace_id,
            "total_files": len(files_list),
            "path_filter": path_filter if path_filter else None,
            "files": files_list
        }
