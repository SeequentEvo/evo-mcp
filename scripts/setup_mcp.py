#!/usr/bin/env python3

# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Evo MCP Configuration Setup
Cross-platform script to configure the Evo MCP server for VS Code or Cursor.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
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

    def __init__(
        self,
        display_name: str,
        client_type: str,
        variant: str,
    ):
        self.display_name = display_name
        self.client_type = client_type
        self.variant = variant


CLIENT_CHOICES = {
    "1": ClientChoice("VS Code", "vscode", "Code"),
    "2": ClientChoice("VS Code Insiders", "vscode", "Code - Insiders"),
    "3": ClientChoice("Cursor", "cursor", "Cursor"),
}

DEFAULT_REDIRECT_URL = "http://localhost:3000/signin-callback"
DEFAULT_HTTP_HOST = "localhost"
DEFAULT_HTTP_PORT = "5000"
TOOL_FILTER_CHOICES = {"1": "all", "2": "admin", "3": "data"}


def print_color(text: str, color: str = Colors.RESET):
    """Print colored text to terminal"""
    print(f"{color}{text}{Colors.RESET}")


def is_confirmed(prompt: str = "Is this correct? [Y/n]: ", default_yes: bool = True) -> bool:
    """Prompt for yes/no confirmation with configurable default."""
    choice = input(prompt).strip().lower()
    if not choice:
        return default_yes
    return choice in ["y", "yes"]


def prompt_choice(
    prompt: str,
    valid_choices: set[str],
    default: str,
    error_message: str,
) -> str:
    """Prompt until the user enters a valid choice."""
    while True:
        choice = input(prompt).strip() or default
        if choice in valid_choices:
            return choice
        print_color(error_message, Colors.RED)


def prompt_for_env_value(
    key: str,
    current_value: str | None,
    description: str,
    default: str = "",
) -> str:
    """Prompt user for an environment variable value."""
    print()
    print(description)

    if current_value and "Replace this" not in current_value:
        print(f"Current value: {current_value}")
        if is_confirmed():
            return current_value

    prompt_text = f"Enter {key} (default: {default}): " if default else f"Enter {key}: "
    while True:
        value = input(prompt_text).strip()
        if value:
            return value
        if default:
            return default
        print_color(f"✗ {key} is required", Colors.RED)


def prompt_with_confirmation(label: str, current_value: str, default: str) -> str:
    """Prompt for a value, optionally accepting the current one."""
    print(f"Current {label}: {current_value}")
    if is_confirmed():
        return current_value
    return input(f"Enter {label} (default: {default}): ").strip() or default


def prompt_tool_filter(current_value: str | None) -> str:
    """Prompt for MCP tool filter selection."""
    print()
    print("Select which tools to enable:")
    print("1. all - All tools (workspace management + data operations)")
    print("2. admin - Workspace/instance management and bulk operations")
    print("3. data - Object import, download and query operations")
    print()

    if current_value:
        print(f"Current value: {current_value}")
        if is_confirmed():
            return current_value

    choice = prompt_choice(
        "Enter your choice [1-3] (default: 1): ",
        set(TOOL_FILTER_CHOICES.keys()),
        "1",
        "Invalid choice. Please enter 1, 2, or 3.",
    )
    return TOOL_FILTER_CHOICES[choice]


def ensure_env_file_exists(project_dir: Path) -> None:
    """Ensure .env file exists, copy from .env.example if not."""
    env_file = project_dir / ".env"
    env_example = project_dir / ".env.example"

    if env_file.exists():
        return

    if not env_example.exists():
        print_color("✗ .env.example not found", Colors.RED)
        sys.exit(1)

    print_color("Creating .env file from .env.example...", Colors.BLUE)
    with open(env_example, "r", encoding="utf-8") as src:
        with open(env_file, "w", encoding="utf-8") as dst:
            dst.write(src.read())
    print_color("✓ Created .env file", Colors.GREEN)


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


def write_env_file(project_dir: Path, values: dict[str, str]) -> None:
    """Write environment values to .env file, preserving comments and structure."""
    env_file = project_dir / ".env"

    lines = []
    if env_file.exists():
        with open(env_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

    updated_keys = set()
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                lines[i] = f"{key}={values[key]}\n"
                updated_keys.add(key)

    for key, value in values.items():
        if key not in updated_keys:
            lines.append(f"{key}={value}\n")

    with open(env_file, "w", encoding="utf-8") as f:
        f.writelines(lines)


def configure_env_settings(project_dir: Path) -> dict[str, str]:
    """Interactively configure environment settings."""

    ensure_env_file_exists(project_dir)
    current_values = load_env_file(project_dir)

    new_values = {}

    new_values["EVO_CLIENT_ID"] = prompt_for_env_value(
        "EVO_CLIENT_ID",
        current_values.get("EVO_CLIENT_ID"),
        "Your Evo application client ID from the iTwin Developer Portal."
    )

    new_values["EVO_REDIRECT_URL"] = prompt_for_env_value(
        "EVO_REDIRECT_URL",
        current_values.get("EVO_REDIRECT_URL"),
        "Your Evo application redirect URL from the iTwin Developer Portal.",
        DEFAULT_REDIRECT_URL,
    )

    new_values["MCP_TOOL_FILTER"] = prompt_tool_filter(current_values.get("MCP_TOOL_FILTER", "all"))

    return new_values


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


def resolve_command_path(command: str, project_dir: Path) -> str:
    """Resolve relative command/script paths against project directory."""
    command_path = Path(command)
    if command_path.is_absolute():
        return str(command_path)
    if command.startswith("./") or command.startswith(".\\"):
        return str((project_dir / command_path).resolve())
    return command


def start_http_server(python_exe: str, mcp_script: str, project_dir: Path) -> int | None:
    """Start Evo MCP HTTP server in the foreground and return exit code."""
    python_command = resolve_command_path(python_exe, project_dir)
    script_command = resolve_command_path(mcp_script, project_dir)

    http_env = get_http_env_from_dotenv(project_dir)
    if http_env is None:
        return None

    env = os.environ.copy()
    env.update(http_env)

    try:
        completed = subprocess.run(
            [python_command, script_command],
            cwd=str(project_dir),
            env=env,
            check=False,
        )
        return completed.returncode
    except KeyboardInterrupt:
        print()
        print_color("HTTP server stopped by user.", Colors.BLUE)
        return 130
    except (OSError, ValueError) as e:
        print_color(f"✗ Failed to start HTTP server: {e}", Colors.RED)
        return None


def get_client_choice() -> ClientChoice:
    """Ask user which client app to configure."""
    print("Which client app are you using?")

    ordered_choices = sorted(CLIENT_CHOICES.items(), key=lambda item: int(item[0]))
    for key, client in ordered_choices:
        suffix = " (recommended)" if key == "1" else ""
        print(f"{key}. {client.display_name}{suffix}")

    print()

    choice_keys = {key for key, _ in ordered_choices}
    choice_list = ", ".join(sorted(choice_keys, key=int))

    choice = prompt_choice(
        f"Enter your choice (default: 1): ",
        choice_keys,
        "1",
        f"Invalid choice. Please enter one of: {choice_list}.",
    )
    return CLIENT_CHOICES[choice]


def get_protocol_choice(
    env_values: dict[str, str],
) -> tuple[str, dict[str, str]]:
    """Ask user which MCP protocol to use and configure HTTP if needed."""
    print()
    print("Which MCP transport protocol are you using?")
    print("1. STDIO (recommended for VS Code/Cursor)")
    print("2. Streamable HTTP (for testing, remote access, Docker)")
    print()

    current_transport = env_values.get("MCP_TRANSPORT", "").lower()
    protocol = None

    if current_transport in ["stdio", "http"]:
        print(f"Current transport: {current_transport.upper()}")
        if is_confirmed():
            protocol = current_transport

    if not protocol:
        choice = prompt_choice(
            "Enter your choice [1-2] (default: 1): ",
            {"1", "2"},
            "1",
            "Invalid choice. Please enter 1 or 2.",
        )
        protocol = "stdio" if choice == "1" else "http"
    
    env_values["MCP_TRANSPORT"] = protocol

    if protocol == "http":
        print()
        print("HTTP Server Configuration:")

        current_host = env_values.get("MCP_HTTP_HOST", DEFAULT_HTTP_HOST)
        env_values["MCP_HTTP_HOST"] = prompt_with_confirmation("host", current_host, DEFAULT_HTTP_HOST)
        print()
        current_port = env_values.get("MCP_HTTP_PORT", DEFAULT_HTTP_PORT)
        env_values["MCP_HTTP_PORT"] = prompt_with_confirmation("port", current_port, DEFAULT_HTTP_PORT)

    return protocol, env_values


def get_start_server_choice() -> bool:
    """Ask whether to start the Evo MCP server now."""
    print()
    print("Would you like to start the Evo MCP server now?")
    print("1. Yes (recommended)")
    print("2. No")
    print()

    choice = prompt_choice(
        "Enter your choice [1-2] (default: 1): ",
        {"1", "2"},
        "1",
        "Invalid choice. Please enter 1 or 2.",
    )
    return choice == "1"


def get_vscode_config_dir(variant: str) -> Path | None:
    """Get the VS Code configuration directory for the current platform."""
    system = platform.system()

    def is_wsl_environment() -> bool:
        if system != "Linux":
            return False
        if os.environ.get("WSL_INTEROP") or os.environ.get("WSL_DISTRO_NAME"):
            return True
        try:
            with open("/proc/sys/kernel/osrelease", "r", encoding="utf-8") as f:
                return "microsoft" in f.read().lower()
        except OSError:
            return False

    if is_wsl_environment():
        candidates: list[Path] = []

        # VS Code Remote - WSL stores user settings in the server data directory.
        agent_folder = os.environ.get("VSCODE_AGENT_FOLDER")
        if agent_folder:
            candidates.append(Path(agent_folder) / "data" / "User")

        if variant == "Code - Insiders":
            candidates.append(Path.home() / ".vscode-server-insiders" / "data" / "User")
        else:
            candidates.append(Path.home() / ".vscode-server" / "data" / "User")

        # Fallback for unusual setups that intentionally write to Windows AppData from WSL.
        win_home = os.environ.get("WIN_HOME")
        if win_home:
            candidates.append(Path(win_home) / "AppData" / "Roaming" / variant / "User")

        for candidate in candidates:
            if candidate.parent.exists():
                print_color(f"Debug: WSL detected, using VS Code config directory: {candidate}", Colors.BLUE)
                return candidate

        checked_paths = ", ".join(str(path) for path in candidates)
        print_color(
            f"Debug: WSL detected, but no VS Code config directory was found. Checked: {checked_paths}",
            Colors.BLUE,
        )
        return None

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


def get_python_executable() -> str:
    """Get the path to the currently running Python executable."""
    return str(Path(sys.executable))


def is_virtual_environment_active() -> bool:
    """Return True when setup is running inside a Python virtual environment."""
    return (
        sys.prefix != getattr(sys, "base_prefix", sys.prefix)
        or bool(os.environ.get("VIRTUAL_ENV"))
    )


def resolve_python_executable(python_command: str) -> str | None:
    """Resolve a Python command to an executable path and verify it is runnable."""
    command = python_command.strip()
    if not command:
        return None

    if not any(sep in command for sep in ["/", "\\"]):
        which = shutil.which(command)
        if which:
            command = which

    try:
        completed = subprocess.run(
            [command, "-c", "import sys; print(sys.executable)"],
            check=False,
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError):
        return None

    if completed.returncode != 0:
        return None

    resolved = completed.stdout.strip().splitlines()
    return resolved[-1] if resolved else None


def choose_python_executable(default_python: str) -> str:
    """Allow the user to confirm or override the Python executable for MCP config."""
    print(f"Current Python interpreter: {default_python}")

    if is_virtual_environment_active():
        print_color("Detected active virtual environment.", Colors.GREEN)
        if is_confirmed("Use this Python interpreter? [Y/n]: "):
            return default_python
    else:
        print_color("Warning: setup is running outside a virtual environment.", Colors.RED)
        print("If Evo MCP dependencies are in a virtual environment, use that interpreter path.")
        if is_confirmed("Use this interpreter anyway? [y/N]: ", default_yes=False):
            return default_python

    while True:
        candidate = input(f"Enter Python executable path (default: {default_python}): ").strip()
        candidate = candidate or default_python
        resolved = resolve_python_executable(candidate)
        if resolved:
            return resolved
        print_color("✗ Python executable not found or not runnable. Please try again.", Colors.RED)


def build_config_entry(
    client: ClientChoice,
    protocol: str,
    python_exe: str,
    mcp_script: str,
    env_values: dict[str, str],
) -> tuple[str, dict]:
    """Build client-specific MCP config entry and top-level key."""
    if client.client_type == "cursor":
        top_level_key = "mcpServers"
        if protocol == "http":
            host = env_values.get("MCP_HTTP_HOST", DEFAULT_HTTP_HOST)
            port = env_values.get("MCP_HTTP_PORT", DEFAULT_HTTP_PORT)
            entry = {"type": "http", "url": f"http://{host}:{port}/mcp"}
        else:
            entry = {"command": python_exe, "args": [mcp_script]}
        return top_level_key, entry

    top_level_key = "servers"
    if protocol == "http":
        host = env_values.get("MCP_HTTP_HOST", DEFAULT_HTTP_HOST)
        port = env_values.get("MCP_HTTP_PORT", DEFAULT_HTTP_PORT)
        entry = {"type": "http", "url": f"http://{host}:{port}/mcp"}
    else:
        entry = {"type": "stdio", "command": python_exe, "args": [mcp_script]}
    return top_level_key, entry


def setup_mcp_config(
    client: ClientChoice,
    protocol: str,
    env_values: dict[str, str],
    start_server_now: bool,
):
    """Set up the MCP configuration for the selected client app."""
    print_color("MCP Client Configuration", Colors.BLUE)
    print("=" * 30)
    print()

    script_dir = Path(__file__).parent.resolve()
    project_dir = script_dir.parent

    config_dir = get_config_dir(client)
    if not config_dir:
        print_color(f"✗ Could not find {client.display_name} installation directory", Colors.RED)
        sys.exit(1)
    config_file = config_dir / "mcp.json"
    print_color(f"Using user configuration for {client.display_name}", Colors.GREEN)

    print(f"Configuration file: {config_file}")
    print()

    python_exe = choose_python_executable(get_python_executable())
    mcp_script = str(project_dir / "src" / "mcp_tools.py")

    config_dir.mkdir(parents=True, exist_ok=True)

    if config_file.exists():
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                raw_config = f.read()

            if raw_config.strip():
                settings = json.loads(raw_config)
            else:
                settings = {}
        except json.JSONDecodeError as e:
            print_color(f"✗ Invalid JSON in existing config file: {e}", Colors.RED)
            print(f"Please fix the syntax error in: {config_file}")
            sys.exit(1)
    else:
        settings = {}

    top_level_key, config_entry = build_config_entry(
        client,
        protocol,
        python_exe,
        mcp_script,
        env_values,
    )

    if top_level_key not in settings:
        settings[top_level_key] = {}

    settings[top_level_key]["evo-mcp"] = config_entry

    try:
        with open(config_file, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)

        server_exit_code = None

        print_color("✓ Successfully added Evo MCP configuration", Colors.GREEN)
        print()
        print("Configuration details:")
        print(f"  Client App: {client.display_name}")
        print(f"  Command: {python_exe}")
        print(f"  Script: {mcp_script}")
        print(f"  Transport Protocol: {protocol.upper()}")
        if protocol == "http":
            http_host = env_values.get("MCP_HTTP_HOST", DEFAULT_HTTP_HOST)
            http_port = env_values.get("MCP_HTTP_PORT", DEFAULT_HTTP_PORT)
            http_url = f"http://{http_host}:{http_port}/mcp"
            print("  HTTP Configuration:")
            print(f"    - Host: {http_host}")
            print(f"    - Port: {http_port}")
            print(f"    - URL: {http_url}")
        print()
        print("Next steps:")
        if protocol == "http" and not start_server_now:
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

        if protocol == "http" and start_server_now:
            print()
            print_color("Starting Evo MCP HTTP server in foreground (Ctrl+C to stop)...", Colors.BLUE)
            server_exit_code = start_http_server(python_exe, mcp_script, project_dir)
            if server_exit_code not in [0, 130, None]:
                print_color(f"✗ HTTP server exited with code {server_exit_code}", Colors.RED)
    except (IOError, OSError) as e:
        print_color(f"✗ Failed to update configuration file: {e}", Colors.RED)
        sys.exit(1)


def main():
    """Main entry point"""
    print_color("Evo MCP Configuration Setup", Colors.BLUE)
    print("=" * 30)

    script_dir = Path(__file__).parent.resolve()
    project_dir = script_dir.parent

    try:
        env_values = configure_env_settings(project_dir)

        print()
        client = get_client_choice()

        print()
        protocol, env_values = get_protocol_choice(env_values)

        write_env_file(project_dir, env_values)
        print()
        print_color("✓ Environment configuration saved to .env", Colors.GREEN)

        start_server_now = False
        if protocol == "http":
            start_server_now = get_start_server_choice()

        print()
        setup_mcp_config(client, protocol, env_values, start_server_now)
    except KeyboardInterrupt:
        print()
        print_color("Setup cancelled by user", Colors.RED)
        sys.exit(1)


if __name__ == "__main__":
    main()

