"""

A FastMCP server that provides tools for interacting with the Evo platform,
including workspace management, object ops, and data transfer.

Configuration:
    Set MCP_TOOL_FILTER environment variable to filter tools and prompts:
    - "admin" : Workspace management tools 
    - "data"  : Object query, file operations, and management tools
    - "all"   : All tools (default)

The environment variable can be set in a .env file or passed directly to the MCP server as an input parameter.
See the file 'vscode-mcp-config-example.json' for an example of passing environment variables to the MCP server.
"""

import os
import logging
from pathlib import Path
from fastmcp import FastMCP
from fastmcp.utilities.logging import configure_logging

from evo_mcp.tools import (
    register_admin_tools,
    # register_data_tools,
    register_general_tools,
    register_filesystem_tools,
    register_object_builder_tools,
    register_file_tools
)

# Get agent type from environment variable 
# Thsi can either be set via MCP inputs, or the .env file used by the agent example
TOOL_FILTER = os.getenv("MCP_TOOL_FILTER", 
    os.getenv(
        "MCP_AGENT_TYPE",  # Kept for backwards compatability
        "all",
    )).lower()
VALID_TOOL_FILTERS = ["admin", "data", "all"]

if TOOL_FILTER not in VALID_TOOL_FILTERS:
    logging.warning(f"Invalid MCP_TOOL_FILTER '{TOOL_FILTER}', defaulting to 'all'")
    TOOL_FILTER = "all"

# Initialize FastMCP server with agent type in name for clarity
server_name = "Evo MCP Server" if TOOL_FILTER == "all" else f"Evo MCP Server ({TOOL_FILTER})"
mcp = FastMCP(server_name)

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
        logging.error(f"Objects reference file not found at {reference_path}")
        return "Objects reference information is currently unavailable."
    
    

# =============================================================================
# Tools - Conditionally registered based on TOOL_FILTER
# =============================================================================

register_general_tools(mcp)  # Always register general tools

if TOOL_FILTER in ["all", "admin"]:  #  "admin_agent"
    register_admin_tools(mcp)
    
if TOOL_FILTER in ["all", "data"]: #  "data_agent"
    # register_data_tools(mcp)
    register_filesystem_tools(mcp)
    register_object_builder_tools(mcp)
    register_file_tools(mcp)

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
    # run the server
    mcp.run()
