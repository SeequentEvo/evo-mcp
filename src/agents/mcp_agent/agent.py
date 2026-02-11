"""
ADK Agent using MCPToolset

This agent uses ADK (Google Agent Development Kit) with the Evo MCP server.
"""

import os
import sys
from pathlib import Path

# Add src directory to Python path (parent of agents folder)
src_dir = Path(__file__).parent.parent.parent
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

from google.adk.planners import PlanReActPlanner
from google.adk.agents import LlmAgent, McpInstructionProvider
from google.adk.tools.mcp_tool.mcp_toolset import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams,StdioServerParameters

from google.adk.auth.auth_credential import AuthCredential
from google.adk.auth.auth_credential import AuthCredentialTypes
from google.adk.tools.openapi_tool.auth.auth_helpers import token_to_scheme_credential
from google.adk.auth.auth_schemes import AuthScheme, AuthSchemeType
from fastapi.openapi.models import APIKey
from fastapi.openapi.models import APIKeyIn
from mcp import StdioServerParameters
from dotenv import load_dotenv

from google.adk.agents.callback_context import CallbackContext
from google.adk.models import LlmResponse

DEFAULT_STDIO_TIMEOUT_SECONDS = 600

# Load environment variables from .env file (go up to repo root)
env_path = Path(__file__).parent.parent.parent.parent / '.env'
if env_path.exists():
    load_dotenv(env_path)

# Agent configuration from environment variables
AGENT_TYPE = os.getenv("MCP_TOOL_FILTER", "workspace") 
MODEL = os.getenv("EVO_AGENT_MODEL", "gemini-3-flash-preview")

# Get the absolute path to the MCP server script (in src directory)
MCP_SERVER_PATH = str(Path(__file__).parent.parent.parent / "mcp_tools.py")


def _generate_dummy_auth():
    """Generate a dummy auth scheme and credential.
    This is just for demonstration purposes and should be replaced with real auth logic."""
    return token_to_scheme_credential(
        "apikey", "header", "apikey", "not a real key"
    )

auth_scheme, auth_credential = _generate_dummy_auth()  

tool_env = {
    # Pass AGENT_TYPE to MCP server for tool filtering
    "MCP_TOOL_FILTER": AGENT_TYPE
}

copy_env_vars = [
    # Display env vars are required on linux (and WSL?) for the `webbrowser`
    # module (used by the Evo SDK authorizor) to open a graphical web browser.
    "DISPLAY",
    "WAYLAND_DISPLAY",
]
for var in copy_env_vars:
    if var in os.environ:
        tool_env[var] = os.environ[var]

server_params=StdioServerParameters(
    command='python',
    args=[MCP_SERVER_PATH],
    env=tool_env,    
)

connection_params=StdioConnectionParams(
    server_params=server_params,
    timeout=DEFAULT_STDIO_TIMEOUT_SECONDS
)

# Use the appropriate prompt based on agent type. The MCP server must provide
# a prompt with the same name as we generate here.
prompt_name = f"{AGENT_TYPE}_prompt"

mcp_instruction=McpInstructionProvider(
    connection_params=connection_params,
    prompt_name=prompt_name,
)

mcp_toolset = McpToolset(
    connection_params=connection_params,
    auth_scheme=auth_scheme, 
    auth_credential=auth_credential,
)

root_agent = LlmAgent(
    model=MODEL,
    name='evo_sdk_agent',
    description='You are a generic agent that receives instructions, tools from an MCP server.',
    global_instruction="IMPORTANT you MUST show your reasoning before calling a tool, and present the plan before performing a workflow.", #  If you are unsure about what to do, STOP and ask for clarification.",
    instruction=mcp_instruction,    
    # planner=PlanReActPlanner(),
    tools=[mcp_toolset]
)
