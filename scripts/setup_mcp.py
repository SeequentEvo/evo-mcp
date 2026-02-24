#!/usr/bin/env python3
"""
Evo MCP Configuration Setup
Cross-platform script to configure the Evo MCP server for VS Code or Cursor.
"""

import json
import os
import platform
import subprocess
import sys
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output"""

    BLUE = "\033[34m"
    GREEN = "\033[32m"
    RED = "\033[31m"
    RESET = "\033[0m"


class ClientChoice:
    """Client app metadata for configuration."""

    def __init__(self, display_name: str, client_type: str, variant: str):
        self.display_name = display_name
        self.client_type = client_type
        self.variant = variant


CLIENT_CHOICES = {
    "1": ClientChoice("VS Code", "vscode", "Code"),
    "2": ClientChoice("VS Code Insiders", "vscode", "Code - Insiders"),
    "3": ClientChoice("Cursor", "cursor", "Cursor"),
}


def print_color(text: str, color: str = Colors.RESET):
    """Print colored text to terminal"""
    print(f"{color}{text}{Colors.RESET}")


def get_vscode_config_dir(variant: str) -> Path | None:
    """Get the VS Code configuration directory for the current platform."""
    system = platform.system()

    if system == "Windows":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            return None
        config_dir = Path(appdata) / variant / "User"
        return config_dir if config_dir.parent.exists() else None

    if system == "Darwin":
        config_dir = Path.home() / "Library" / "Application Support" / variant / "User"
        return config_dir if config_dir.parent.exists() else None

    if system == "Linux":
        config_dir = Path.home() / ".config" / variant / "User"
        return config_dir if config_dir.parent.exists() else None

    return None


def get_cursor_config_dir(variant: str) -> Path | None:
    """Get the Cursor configuration directory for the current platform."""
    system = platform.system()

    if system == "Windows":
        return Path.home() / ".cursor"

    if system == "Darwin":
        config_dir = Path.home() / ".cursor"
        return config_dir if config_dir.exists() else None

    if system == "Linux":
        config_dir = Path.home() / ".config" / variant / "User"
        return config_dir if config_dir.parent.exists() else None

    return None


def get_config_dir(client: ClientChoice) -> Path | None:
    """Resolve client config directory based on chosen app."""
    if client.client_type == "vscode":
        return get_vscode_config_dir(client.variant)
    return get_cursor_config_dir(client.variant)


def find_venv_python(project_dir: Path) -> Path | None:
    """Try to find a virtual environment in the project directory"""
    system = platform.system()
    venv_names = [".venv", "venv", "env"]

    for venv_name in venv_names:
        if system == "Windows":
            python_path = project_dir / venv_name / "Scripts" / "python.exe"
        else:
            python_path = project_dir / venv_name / "bin" / "python"

        if python_path.exists():
            return python_path

    return None


def get_python_executable(project_dir: Path, is_workspace: bool) -> str:
    """
    Get the path to the Python executable.
    Uses the currently running Python interpreter, or tries to find a venv.
    """
    current_python = Path(sys.executable)

    if is_workspace:
        try:
            rel_path = current_python.relative_to(project_dir)
            return "./" + str(rel_path).replace("\\", "/")
        except ValueError:
            venv_python = find_venv_python(project_dir)
            if venv_python:
                try:
                    rel_path = venv_python.relative_to(project_dir)
                    return "./" + str(rel_path).replace("\\", "/")
                except ValueError:
                    pass
            return str(current_python)

    return str(current_python)


def resolve_command_path(command: str, project_dir: Path) -> str:
    """Resolve relative command/script paths against project directory."""
    command_path = Path(command)
    if command_path.is_absolute():
        return str(command_path)
    if command.startswith("./") or command.startswith(".\\"):
        return str((project_dir / command_path).resolve())
    return command


def load_env_file(project_dir: Path) -> dict[str, str]:
    """Load key/value pairs from the project's .env file."""
    env_file = project_dir / ".env"
    values: dict[str, str] = {}

    if not env_file.exists():
        return values

    with open(env_file, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("export "):
                line = line[len("export ") :].strip()

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key:
                values[key] = value

    return values


def get_http_env_from_dotenv(project_dir: Path) -> dict[str, str] | None:
    """Read required HTTP server environment values from .env."""
    env_values = load_env_file(project_dir)
    required_keys = ["MCP_TRANSPORT", "MCP_HTTP_HOST", "MCP_HTTP_PORT"]
    missing_keys = [key for key in required_keys if not env_values.get(key)]

    if missing_keys:
        print_color("✗ Cannot auto-start HTTP server. Missing required values in .env:", Colors.RED)
        for key in missing_keys:
            print_color(f"  - {key}", Colors.RED)
        return None

    transport = env_values["MCP_TRANSPORT"].lower()
    if transport != "http":
        print_color("✗ Cannot auto-start HTTP server. Set MCP_TRANSPORT=http in .env.", Colors.RED)
        return None

    return {
        "MCP_TRANSPORT": env_values["MCP_TRANSPORT"],
        "MCP_HTTP_HOST": env_values["MCP_HTTP_HOST"],
        "MCP_HTTP_PORT": env_values["MCP_HTTP_PORT"],
    }


def start_http_server(python_exe: str, mcp_script: str, project_dir: Path) -> int | None:
    """Start Evo MCP HTTP server in the background. Returns PID if successful."""
    python_command = resolve_command_path(python_exe, project_dir)
    script_command = resolve_command_path(mcp_script, project_dir)

    http_env = get_http_env_from_dotenv(project_dir)
    if http_env is None:
        return None

    env = os.environ.copy()
    env.update(http_env)

    popen_kwargs = {
        "cwd": str(project_dir),
        "env": env,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }

    if platform.system() == "Windows":
        popen_kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["start_new_session"] = True

    try:
        process = subprocess.Popen([python_command, script_command], **popen_kwargs)
        return process.pid
    except (OSError, ValueError) as e:
        print_color(f"✗ Failed to start HTTP server automatically: {e}", Colors.RED)
        return None


def get_client_choice() -> ClientChoice:
    """Ask user which client app to configure."""
    print("Which client app are you using?")
    print("1. VS Code (recommended)")
    print("2. VS Code Insiders")
    print("3. Cursor")
    print()

    while True:
        choice = input("Enter your choice [1-3] (default: 1): ").strip()
        if not choice:
            choice = "1"

        if choice in CLIENT_CHOICES:
            return CLIENT_CHOICES[choice]

        print_color("Invalid choice. Please enter 1, 2, or 3.", Colors.RED)
        print()


def get_protocol_choice() -> str:
    """Ask user which MCP protocol to use"""
    print()
    print("Which MCP transport protocol are you using?")
    print("1. stdio (recommended for VS Code/Cursor)")
    print("   - Native IDE integration")
    print("   - Best performance for local development")
    print("2. Streamable HTTP (for testing, remote access, Docker)")
    print("   - Easier debugging and testing")
    print("   - Can run on remote servers")
    print()

    while True:
        choice = input("Enter your choice [1-2] (default: 1): ").strip()
        if not choice:
            choice = "1"

        if choice in ["1", "2"]:
            return "stdio" if choice == "1" else "http"

        print_color("Invalid choice. Please enter 1 or 2.", Colors.RED)
        print()


def build_config_entry(client: ClientChoice, protocol: str, python_exe: str, mcp_script: str) -> tuple[str, dict]:
    """Build client-specific MCP config entry and top-level key."""
    if client.client_type == "cursor":
        top_level_key = "mcpServers"
        if protocol == "http":
            entry = {"type": "http", "url": "http://localhost:5000/mcp"}
        else:
            entry = {"command": python_exe, "args": [mcp_script]}
        return top_level_key, entry

    top_level_key = "servers"
    if protocol == "http":
        entry = {"type": "http", "url": "http://localhost:5000/mcp"}
    else:
        entry = {"type": "stdio", "command": python_exe, "args": [mcp_script]}
    return top_level_key, entry


def setup_mcp_config(client: ClientChoice, protocol: str = "stdio"):
    """Set up the MCP configuration for the selected client app."""
    print_color("Evo MCP Configuration Setup", Colors.BLUE)
    print("=" * 30)
    print()

    script_dir = Path(__file__).parent.resolve()
    project_dir = script_dir.parent

    config_type = "user"
    is_workspace = config_type == "workspace"

    if is_workspace:
        config_dir = Path(".vscode")
        config_file = config_dir / "mcp.json"
    else:
        config_dir = get_config_dir(client)
        if not config_dir:
            print_color(f"✗ Could not find {client.display_name} installation directory", Colors.RED)
            sys.exit(1)
        config_file = config_dir / "mcp.json"
        print_color(f"Using user configuration for {client.display_name}", Colors.GREEN)

    print(f"Configuration file: {config_file}")
    print()

    python_exe = get_python_executable(project_dir, is_workspace)
    mcp_script = str(project_dir / "src" / "mcp_tools.py")

    config_dir.mkdir(parents=True, exist_ok=True)

    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except json.JSONDecodeError as e:
            print_color(f"✗ Invalid JSON in existing config file: {e}", Colors.RED)
            print(f"Please fix the syntax error in: {config_file}")
            sys.exit(1)
    else:
        settings = {}

    top_level_key, config_entry = build_config_entry(client, protocol, python_exe, mcp_script)

    if top_level_key not in settings:
        settings[top_level_key] = {}

    settings[top_level_key]["evo-mcp"] = config_entry

    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

        server_pid = None
        if protocol == "http":
            print("Starting Evo MCP HTTP server in background...")
            server_pid = start_http_server(python_exe, mcp_script, project_dir)

        print_color("✓ Successfully added Evo MCP configuration", Colors.GREEN)
        print()
        print("Configuration details:")
        print(f"  Client App: {client.display_name}")
        print(f"  Command: {python_exe}")
        print(f"  Script: {mcp_script}")
        print(f"  Transport Protocol: {protocol.upper()}")
        if protocol == "http":
            print("  HTTP Configuration:")
            print("    - Host: localhost")
            print("    - Port: 5000")
            if server_pid:
                print("    - URL: http://localhost:5000/mcp")
                print(f"    - Background PID: {server_pid}")
        print()
        print("Next steps:")
        if protocol == "http" and server_pid is None:
            print("Ensure .env contains MCP_TRANSPORT, MCP_HTTP_HOST, and MCP_HTTP_PORT for HTTP mode.")
            print("Start Evo MCP server manually:")
            print(f"  {python_exe} {mcp_script}")

        if client.client_type == "cursor":
            print("Restart Cursor or reload the window")
        else:
            print("Restart VS Code or reload the window")

        print()
        print("Note: This configuration uses the Python interpreter:")
        print(f"  {python_exe}")
        print("If you need to use a different Python environment, activate it")
        print("and run this setup script again.")
    except (IOError, OSError) as e:
        print_color(f"✗ Failed to update configuration file: {e}", Colors.RED)
        sys.exit(1)


def main():
    """Main entry point"""
    print_color("Evo MCP Configuration Setup", Colors.BLUE)
    print("=" * 30)
    print()

    try:
        client = get_client_choice()
        print()
        protocol = get_protocol_choice()
        print()
        setup_mcp_config(client, protocol)
    except KeyboardInterrupt:
        print()
        print_color("Setup cancelled by user", Colors.RED)
        sys.exit(1)


if __name__ == "__main__":
    main()
