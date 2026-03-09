# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
A FastMCP server that provides tools for interacting with the Evo platform,
including workspace management, object ops, and data transfer.

Configuration:
    Set MCP_TOOL_FILTER environment variable to filter tools and prompts:
    - "admin" : Workspace management tools 
    - "data"    : Object query and management tools 
    - "all"       : All tools (default)

    Set MCP_TRANSPORT environment variable to choose transport mode:
    - "stdio" (default): Standard input/output, used by VS Code, Cursor, Claude Desktop
    - "http": Streamable HTTP, accessible via HTTP requests

    For HTTP transport, configure:
    - MCP_HTTP_HOST: Host to bind to (default: localhost)
    - MCP_HTTP_PORT: Port to listen on (default: 5000)

    Logging configuration:
    - MCP_LOG_LEVEL: Python logging level (default: INFO)
    - MCP_LOG_FILE: Optional log file path for server logs

The environment variables can be set in a .env file or 
passed directly to the MCP server as input parameters.
"""

import os
import logging
from pathlib import Path
from fastmcp import FastMCP
from fastmcp.utilities.logging import configure_logging, get_logger
from evo_mcp.env import load_repo_env

from evo_mcp.tools import (
    register_admin_tools,
    # register_data_tools,
    register_general_tools,
    register_filesystem_tools,
    register_object_builder_tools,
    register_instance_users_admin_tools,
)

# Load environment variables from .env in the repo root.
load_repo_env()

# Use the actual FastMCP root logger so all fastmcp.* module loggers inherit
# handlers (including optional file output).
BASE_LOGGER = logging.getLogger("fastmcp")
LOGGER = get_logger(__name__)
VALID_LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}

# Get transport mode from environment variable
TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio").lower()
VALID_TRANSPORTS = ["stdio", "http"]

if TRANSPORT not in VALID_TRANSPORTS:
    LOGGER.warning("Invalid MCP_TRANSPORT '%s', defaulting to 'stdio'", TRANSPORT)
    TRANSPORT = "stdio"

# Get logging level from environment variable
LOG_LEVEL_NAME = os.getenv("MCP_LOG_LEVEL", "INFO").upper()
if LOG_LEVEL_NAME not in VALID_LOG_LEVELS:
    LOGGER.warning("Invalid MCP_LOG_LEVEL '%s', defaulting to 'INFO'", LOG_LEVEL_NAME)
    LOG_LEVEL_NAME = "INFO"

# Get HTTP configuration if using HTTP transport
if TRANSPORT == "http":
    HTTP_HOST = os.getenv("MCP_HTTP_HOST", "localhost")
    HTTP_PORT = int(os.getenv("MCP_HTTP_PORT", "5000"))

# Get agent type from environment variable
# This can either be set via MCP inputs, or the .env file used by the agent example
TOOL_FILTER = os.getenv("MCP_TOOL_FILTER",
    os.getenv(
        "MCP_AGENT_TYPE",  # Kept for backwards compatibility
        "all",
    )).lower()
VALID_TOOL_FILTERS = ["admin", "data", "all"]

if TOOL_FILTER not in VALID_TOOL_FILTERS:
    LOGGER.warning("Invalid MCP_TOOL_FILTER '%s', defaulting to 'all'", TOOL_FILTER)
    TOOL_FILTER = "all"

# Initialize FastMCP server with agent type in name for clarity
server_name = "Evo MCP Server" if TOOL_FILTER == "all" else f"Evo MCP Server ({TOOL_FILTER})"
mcp = FastMCP(server_name)

# Show more traceback frame for now, we may want to disabled the rich
# traceback formatting entirely too.
configure_logging(
    logger=BASE_LOGGER,
    level=LOG_LEVEL_NAME,
    tracebacks_max_frames=20,
)

LOG_FILE = os.getenv("MCP_LOG_FILE", "").strip()
if LOG_FILE:
    try:
        log_path = Path(LOG_FILE).expanduser()
        if not log_path.is_absolute():
            log_path = (Path(__file__).parent.parent / log_path).resolve()
        if log_path.parent and not log_path.parent.exists():
            log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setLevel(getattr(logging, LOG_LEVEL_NAME, logging.INFO))
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s")
        )
        BASE_LOGGER.addHandler(file_handler)
        LOGGER.info("File logging enabled: %s", log_path)
    except Exception as e:
        LOGGER.warning("Failed to configure MCP_LOG_FILE '%s': %s", LOG_FILE, e)

def _get_objects_reference_content() -> str:
    """Load the objects reference content from a markdown file."""
    reference_path = Path(__file__).parent / "evo_mcp" / "OBJECTS.md"
    try:
        with open(reference_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        LOGGER.error("Objects reference file not found at %s", reference_path)
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
    if TOOL_FILTER == "data":
        LOGGER.info("Evo MCP Server configured for Data Agent")
    else:
        LOGGER.info("Evo MCP Server configured - Data tools enabled")

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
    LOGGER.info("Registering prompt for all tool types.")
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
# via ensure_initialized() because OAuth requires browser interaction
# =============================================================================
# Main Entry Point
# =============================================================================

if __name__ == "__main__":
    # Log startup information
    LOGGER.info("Starting Evo MCP Server in %s mode", TRANSPORT.upper())

    # Run the server with selected transport mode
    if TRANSPORT == "http":
        LOGGER.info("HTTP server will listen on %s:%s", HTTP_HOST, HTTP_PORT)
        mcp.run(
            transport="http",
            host=HTTP_HOST,
            port=HTTP_PORT,
        )
    else:
        # Default STDIO mode
        mcp.run()
