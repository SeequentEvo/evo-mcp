# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Hosted file tools using binary HTTP transfers, not model-carried file content."""

from uuid import UUID

from evo_mcp.context import get_evo_context
from evo_mcp.file_transfer import register_file_transfer_routes
from evo_mcp.tools.file_tools import register_file_catalog_tools
from evo_mcp.tools.filesystem_tools import register_csv_preview_tools

FILE_TRANSFER_INSTRUCTIONS = """\
Hosted file input/output:
- The server cannot open paths on the user's machine. Use existing client tools
  to discover local files and transfer their original bytes, with normal user
  permissions. Do not install a connector, reconstruct attachments, or put file
  content/base64 into the conversation.
- For input, obtain the original file's byte size and SHA-256 using client tools,
  then call `prepare_file_upload`. Send the file as the raw HTTP request body to
  the returned URL using its method and headers (not multipart form data).
  Require a successful response with status `received` before using `file_ref`.
- To save the file into an Evo workspace, call `upload_file` with `file_ref`.
  For CSV preview, builders, or staged point-set creation, instead pass `file_ref`
  as the existing file parameter. Transfer each CSV separately. Temporary input
  does not create an Evo workspace file, including during dry-run validation.
  Completed input expires after 15 minutes without use. Re-upload if it expires.
  If a workspace upload's result is uncertain, inspect the workspace before
  retrying: the first attempt may already have created a file version.
- For output, `download_file` prepares a download; it does NOT save the file.
  Use existing client tools to stream its URL to the user's chosen destination
  (or the client's supported downloadable attachment location). Require HTTP
  success and check the byte size before reporting completion. Confirm before
  overwriting an existing local file.
- Treat transfer credentials and signed URLs as secrets. Do not print them in
  chat, follow redirects with credentials, or send MCP/OAuth/API-key credentials
  to transfer URLs. Use only the returned transfer headers.
- If an attachment's original bytes, filesystem access, or binary HTTP tools are
  unavailable, explain that client limitation. Never claim a transfer succeeded
  merely because a URL was prepared. Local examples in prompts refer to client
  paths: in hosted CSV tool calls, replace them with uploaded `file_ref` values.
"""


def register_remote_input_tools(mcp, public_base_url: str) -> None:
    """Register temporary input and CSV preview for data and staging tools."""
    register_file_transfer_routes(mcp)
    register_csv_preview_tools(mcp)

    @mcp.tool()
    async def prepare_file_upload(file_name: str, size_bytes: int, sha256: str) -> dict:
        """Prepare a temporary binary file upload for this MCP session.

        Compute size_bytes and SHA-256 from the original client file. Use existing
        client HTTP/shell tools to PUT its raw bytes to the returned URL with the
        returned headers. Do not send base64 or multipart data. After HTTP success
        (`status=received`), pass file_ref to upload_file or any CSV input parameter.
        This does not create a workspace file. If the client cannot access the
        original bytes or perform binary HTTP transfers, report that limitation.
        """
        context = await get_evo_context()
        result = context.file_transfers.prepare(file_name, size_bytes, sha256)
        return {**result, "url": f"{public_base_url.rstrip('/')}/file-transfer"}


def register_remote_file_tools(mcp) -> None:
    """Register workspace transfers without exposing server-local paths."""

    @mcp.tool()
    async def upload_file(workspace_id: str, file_ref: str, target_path: str = "") -> dict:
        """Save a completed temporary upload into an Evo workspace.

        First use prepare_file_upload and transfer the original bytes with the
        client's existing HTTP tools. file_ref is its returned upload reference,
        never a client-local path. target_path is an optional workspace folder.
        """
        context = await get_evo_context()
        with context.file_transfers.use(file_ref) as local_path:
            size_bytes = local_path.stat().st_size
            workspace_path = (
                f"/{target_path.strip('/')}/{local_path.name}" if target_path.strip("/") else f"/{local_path.name}"
            )
            client = await context.get_file_client(UUID(workspace_id))
            upload = await client.prepare_upload_by_path(workspace_path)
            await upload.upload_from_path(str(local_path), context.connector.transport)
        return {
            "status": "uploaded",
            "file_id": str(upload.file_id),
            "path": workspace_path,
            "version_id": upload.version_id,
            "size_bytes": size_bytes,
        }

    @mcp.tool()
    async def download_file(workspace_id: str, file_path: str, version: str = "") -> dict:
        """Prepare a workspace file download, optionally for a specific version.

        Use existing client HTTP/shell tools to GET the returned URL into the
        user's chosen local destination or a downloadable client attachment.
        Do not print file bytes in chat. Confirm HTTP success and the expected
        byte size before reporting completion; preparing this URL is not a
        completed download. Confirm before overwriting an existing local file.
        """
        file_path = file_path if file_path.startswith("/") else f"/{file_path}"
        context = await get_evo_context()
        client = await context.get_file_client(UUID(workspace_id))
        download = await client.prepare_download_by_path(file_path, version_id=version or None)
        return {
            "status": "download_ready",
            "file_path": file_path,
            "file_name": download.metadata.name,
            "version_id": download.metadata.version_id,
            "size_bytes": download.metadata.size,
            "url": await download.get_download_url(),
            "method": "GET",
            "headers": {},
        }

    register_file_catalog_tools(mcp)
