# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
A FastMCP server that provides tools for interacting with the Evo platform,
including workspace management, object ops, and data transfer.

Configuration:
    Set MCP_TOOL_FILTER environment variable to filter tools and prompts:
    - "admin" : Workspace management tools 
    - "data"  : Object query, file operations, and management tools
    - "all"   : All tools (default)

    Set MCP_TRANSPORT environment variable to choose transport mode:
    - "stdio" (default): Standard input/output, used by VS Code, Cursor, Claude Desktop
    - "http": Streamable HTTP, accessible via HTTP requests

    For HTTP transport, configure:
    - MCP_HTTP_HOST: Host to bind to (default: localhost)
    - MCP_HTTP_PORT: Port to listen on (default: 5000)

The environment variables can be set in a .env file or 
passed directly to the MCP server as input parameters.
"""

import json as _json
import logging
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.utilities.logging import configure_logging
from starlette.middleware import Middleware
from starlette.types import ASGIApp, Receive, Scope, Send

from evo_mcp.client_auth import create_auth_provider
from evo_mcp.tools import (
    register_admin_tools,
    # register_data_tools,
    register_general_tools,
    register_filesystem_tools,
    register_object_builder_tools,
    register_file_tools,
    register_instance_users_admin_tools
)

# Get transport mode from environment variable
TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio").lower()
VALID_TRANSPORTS = ["stdio", "http"]

if TRANSPORT not in VALID_TRANSPORTS:
    logging.warning("Invalid MCP_TRANSPORT '%s', defaulting to 'stdio'", TRANSPORT)
    TRANSPORT = "stdio"

# Get HTTP configuration if using HTTP transport
HTTP_HOST = os.getenv("MCP_HTTP_HOST", "localhost")
HTTP_PORT = int(os.getenv("MCP_HTTP_PORT", "5000"))

# Whether to enable OAuth authentication for HTTP transport.
# When enabled, the server acts as an OIDC proxy: MCP clients authenticate
# via an OAuth browser flow (Dynamic Client Registration + PKCE), and the
# server validates each request's token before forwarding it to Evo APIs.
# This enables client-delegated auth — each connected client authenticates
# independently and sees only the instances/workspaces their account has access to.
#
# Disable if:
#   - The server is behind a reverse proxy that already enforces auth
#   - You are doing local development and don't want to deal with OAuth
#   - You want server-managed auth (set AUTH_METHOD=client_credentials or
#     native_app and let the server handle authentication)
#
# Defaults to False. Set to true only when MCP_TRANSPORT=http.

if os.getenv("CLIENT_DELEGATED_AUTH", "").lower()in ("1", "true", "yes"):
    CLIENT_DELEGATED_AUTH = True
else:
    CLIENT_DELEGATED_AUTH = False  # default: off unless explicitly enabled

if CLIENT_DELEGATED_AUTH and TRANSPORT != "http":
    logging.warning(
        "CLIENT_DELEGATED_AUTH=true has no effect with MCP_TRANSPORT='%s' — "
        "OAuth authentication is only supported with HTTP transport. Ignoring.",
        TRANSPORT,
    )
    CLIENT_DELEGATED_AUTH = False

# Get agent type from environment variable
# This can either be set via MCP inputs, or the .env file used by the agent example
TOOL_FILTER = os.getenv("MCP_TOOL_FILTER",
    os.getenv(
        "MCP_AGENT_TYPE",  # Kept for backwards compatibility
        "all",
    )).lower()
VALID_TOOL_FILTERS = ["admin", "data", "all"]

if TOOL_FILTER not in VALID_TOOL_FILTERS:
    logging.warning("Invalid MCP_TOOL_FILTER '%s', defaulting to 'all'", TOOL_FILTER)
    TOOL_FILTER = "all"





# Initialize FastMCP server with agent type in name for clarity
server_name = "Evo MCP Server" if TOOL_FILTER == "all" else f"Evo MCP Server ({TOOL_FILTER})"
auth_provider = create_auth_provider(f"http://{HTTP_HOST}:{HTTP_PORT}") if CLIENT_DELEGATED_AUTH else None
mcp = FastMCP(server_name, auth=auth_provider)

# Show more traceback frame for now, we may want to disabled the rich
# traceback formatting entirely too.
configure_logging(tracebacks_max_frames=20)

def _get_objects_reference_content() -> str:
    """Load the objects reference content from a markdown file."""
    reference_path = Path(__file__).parent / "evo_mcp" / "OBJECTS.md"
    try:
        with open(reference_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        logging.error("Objects reference file not found at %s", reference_path)
        return "Objects reference information is currently unavailable."


# =============================================================================
# Tools - Conditionally registered based on TOOL_FILTER
# =============================================================================

# Always register general tools (workspace discovery, object queries, etc.)
register_general_tools(mcp)

if TOOL_FILTER in ["all", "admin"]:
    # Admin Agent: Workspace and instance management tools
    # Includes: workspace creation, snapshots, duplication, permissions management
    register_admin_tools(mcp)
    register_instance_users_admin_tools(mcp)
if TOOL_FILTER in ["all", "data"]: #  "data_agent"
    # register_data_tools(mcp)
    register_filesystem_tools(mcp)
    register_object_builder_tools(mcp)
    register_file_tools(mcp)
    if TOOL_FILTER == "data":
        print("Evo MCP Server configured for Data Agent")
    else:
        print("Evo MCP Server configured - Data tools enabled")

# =============================================================================
# Resources (not currently supported in ADK)
# =============================================================================

@mcp.resource("evo://objects/schema-reference")
def get_objects_reference() -> str:
    """
    Comprehensive technical reference for Evo Geoscience Objects (GOs).
    
    Provides detailed schema information for all available geoscience object types,
    including required and optional parameters for each object type.
    """
    return _get_objects_reference_content()


# =============================================================================
# Prompts - Conditionally registered based on TOOL_FILTER
# =============================================================================

if TOOL_FILTER == "all":
    print("Registering prompt for all tool types.")
    @mcp.prompt(name="all_prompt")
    def all_prompt() -> str:
        """All prompt that encompasses the functionality of all tool without a filter applied."""
        return """\
        You are an assistant for the Evo platform created by Seequent.
        You can help users with:
        - Listing and discovering workspaces
        - Getting workspace details and statistics
        - Creating new workspaces
        - Managing workspace metadata
        - Managing user permissions and access control
        - Health checks and status monitoring
        - Selecting instances (organizations) to work with
        - Listing and searching for objects within workspaces
        - Retrieving object details and content
        - Creating new objects
        - Managing object versions
        - Extracting data blob references
        - Answering questions about data formats and schemas
        - Copying objects between workspaces
        - Duplicating entire workspaces with optional filtering
        - Bulk operations on multiple objects
        - Data migration and backup operations
        - Listing users in the instance and their roles
        - Adding or removing users from the instance
        - Updating user roles in the instance

        When a user asks about workspaces, use the available MCP tools to provide accurate information.
        Always be clear about what workspace you're working with.
        If you need a workspace_id, ask the user or list workspaces first.

        When working with objects, always verify workspace_id and object_id.
        Use the Object Information reference below to understand object schemas and required properties.

        Use the powerful bulk operation capabilities carefully. Always confirm the scope of operations with users.
        Available tools:

        Safety guidelines:
        - Confirm before deleting objects
        - Verify required properties when creating objects
        - Check object schema compatibility


        """


# Register prompts based on agent type
if TOOL_FILTER in ["all", "admin"]:
    @mcp.prompt(name="admin_prompt")
    def admin_prompt() -> str:
        """Prompt for management operations."""
        return """\
        You are an admin assistant for Evo workspace management created by Seequent.

        You can help users with:
        - Listing and discovering workspaces
        - Getting workspace details and statistics
        - Creating new workspaces
        - Managing workspace metadata
        - Managing user permissions and access control
        - Health checks and status monitoring
        - Selecting instances (organizations) to work with

        When a user asks about workspaces, use the available MCP tools to provide accurate information.
        Always be clear about what workspace you're working with.
        If you need a workspace_id, ask the user or list workspaces first.

        If an error occurs when calling a tool, return the full error message to help troubleshoot.
        """


if TOOL_FILTER in ["all", "data"]:
    @mcp.prompt(name="data_prompt")
    def data_prompt() -> str:
        """Prompt for local file system data connector and object creation operations."""
        return """\
        You are a local data import specialist for the Evo platform created by Seequent.

        You can help users create geoscience objects from CSV files.

        ## Supported Object Types

        | Type | File Pattern | Use Case |
        |------|--------------|----------|
        | **Pointset** | Single CSV with X/Y/Z | Sample locations, sensors |
        | **LineSegments** | Vertices CSV + Segments CSV | Faults, contacts, lines |
        | **DownholeCollection** | Collar + Survey + Intervals | Drillhole data |

        ## Recommended Workflow

        ### Step 1: Discover Files
        ```
        list_local_data_files(file_pattern="*.csv")
        ```

        ### Step 2: Analyze Files (Optional)
        ```
        preview_csv_file(file_path="file1.csv")
        ```
        This shows column names and data types to help determine column mappings.

        ### Step 3: Create Object (use the appropriate tool for your data type)

        #### For Pointset (single CSV with coordinates):
        ```
        build_and_create_pointset(
            workspace_id="<uuid>",
            object_path="/data/my_pointset.json",
            object_name="My Pointset",
            description="Sample locations",
            csv_file="points.csv",
            x_column="X",
            y_column="Y",
            z_column="Z",
            dry_run=True  # Validate first
        )
        ```

        #### For LineSegments (vertices + segments CSVs):
        ```
        build_and_create_line_segments(
            workspace_id="<uuid>",
            object_path="/data/my_lines.json",
            object_name="My Lines",
            description="Fault traces",
            vertices_file="vertices.csv",
            segments_file="segments.csv",
            x_column="X",
            y_column="Y",
            z_column="Z",
            start_index_column="start_idx",
            end_index_column="end_idx",
            dry_run=True  # Validate first
        )
        ```

        #### For DownholeCollection (collar + survey + intervals):
        ```
        build_and_create_downhole_collection(
            workspace_id="<uuid>",
            object_path="/drillholes/my_drillholes.json",
            object_name="My Drillholes",
            description="Exploration drilling",
            collar_file="collar.csv",
            survey_file="survey.csv",
            collar_id_column="HOLE_ID",
            survey_id_column="HOLE_ID",
            x_column="X",
            y_column="Y",
            z_column="Z",
            depth_column="DEPTH",
            azimuth_column="AZIMUTH",
            dip_column="DIP",
            interval_files=[
                {
                    "file": "assay.csv",
                    "name": "assay",
                    "id_column": "HOLE_ID",
                    "from_column": "FROM",
                    "to_column": "TO"
                }
            ],
            dry_run=True  # Validate first
        )
        ```

        ### Step 4: Create (after validation)
        Run the same command with `dry_run=False` to create the object.

        ## Best Practices

        1. **Always use dry_run=True first** - validates without creating
        2. **Check column names** - use preview_csv_file to see available columns
        3. **Review warnings** - understand data quality before proceeding

        If an error occurs when calling a tool, return the full error message.
        """
    

# Note: Evo context initialization happens lazily on first tool call
# via get_evo_context() because OAuth requires browser interaction
# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Log startup information
    logger = logging.getLogger(__name__)
    logger.info("Starting Evo MCP Server in %s mode", TRANSPORT.upper())

    # Run the server with selected transport mode
    if TRANSPORT == "http":

        class AuthMetadataPatchMiddleware:
            """Patches the OAuth metadata to advertise 'none' as a supported
            token endpoint auth method, which is required for public MCP
            clients (like VS Code) that don't have a client secret.

            The MCP SDK hardcodes only ["client_secret_post", "client_secret_basic"],
            but the OIDCProxy's DCR endpoint actually accepts "none".
            """

            def __init__(self, app: ASGIApp) -> None:
                self.app = app

            async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
                if scope["type"] != "http":
                    await self.app(scope, receive, send)
                    return

                path = scope.get("path", "")
                method = scope.get("method", "?")
                print(f"[req] {method} {path}", flush=True)

                if not path.startswith("/.well-known/oauth-authorization-server"):
                    await self.app(scope, receive, send)
                    return

                # Capture response body, patch token_endpoint_auth_methods_supported
                response_body = bytearray()
                response_started = False
                original_headers = []
                original_status = 200

                async def capture_send(message):
                    nonlocal response_started, original_headers, original_status
                    if message["type"] == "http.response.start":
                        response_started = True
                        original_status = message.get("status", 200)
                        original_headers = list(message.get("headers", []))
                    elif message["type"] == "http.response.body":
                        response_body.extend(message.get("body", b""))

                await self.app(scope, receive, capture_send)

                try:
                    data = _json.loads(bytes(response_body))
                    methods = data.get("token_endpoint_auth_methods_supported", [])
                    if "none" not in methods:
                        methods.append("none")
                        data["token_endpoint_auth_methods_supported"] = methods
                    patched = _json.dumps(data).encode()

                    # Update content-length header
                    new_headers = [
                        (k, v) for k, v in original_headers
                        if k != b"content-length"
                    ]
                    new_headers.append(
                        (b"content-length", str(len(patched)).encode())
                    )

                    await send({
                        "type": "http.response.start",
                        "status": original_status,
                        "headers": new_headers,
                    })
                    await send({
                        "type": "http.response.body",
                        "body": patched,
                    })
                    print(f"[req] Patched auth metadata: added 'none' to token_endpoint_auth_methods_supported", flush=True)
                except Exception:
                    # If parsing fails, send original response unchanged
                    await send({
                        "type": "http.response.start",
                        "status": original_status,
                        "headers": original_headers,
                    })
                    await send({
                        "type": "http.response.body",
                        "body": bytes(response_body),
                    })

        logger.info("HTTP server will listen on %s:%s", HTTP_HOST, HTTP_PORT)
        mcp.run(
            transport="http",
            host=HTTP_HOST,
            port=HTTP_PORT,
            log_level="debug",
            middleware=[Middleware(AuthMetadataPatchMiddleware)],
        )
    else:
        # Default STDIO mode
        mcp.run()
