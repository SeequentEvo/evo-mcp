#!/usr/bin/env python3
"""
Evo MCP Configuration Setup for Cursor
Cross-platform script to configure the Evo MCP server for Cursor
"""

import json
import platform
import sys
from pathlib import Path


class Colors:
    """ANSI color codes for terminal output"""
    BLUE = '\033[34m'
    GREEN = '\033[32m'
    RED = '\033[31m'
    RESET = '\033[0m'


def print_color(text: str, color: str = Colors.RESET):
    """Print colored text to terminal"""
    print(f"{color}{text}{Colors.RESET}")


def get_config_dir(variant: str | None = None) -> Path | None:
    """
    Get the Cursor configuration directory for the current platform.
    
    Args:
        variant: Cursor variant ('Cursor' or 'Cursor Nightly')
    """
    system = platform.system()
    
    variants = ['Cursor Nightly', 'Cursor'] if not variant else [variant]
    
    if system == 'Windows':
        home = Path.home()
        config_dir = home / '.cursor'
        return config_dir
    
    elif system == 'Darwin':  # macOS
        home = Path.home()
        config_dir = home / '.cursor'
        if config_dir.exists():
            return config_dir
    
    elif system == 'Linux':
        home = Path.home()
        for v in variants:
            config_dir = home / '.config' / v / 'User'
            if config_dir.parent.exists():
                return config_dir
    
    return None


def find_venv_python(project_dir: Path) -> Path | None:
    """Try to find a virtual environment in the project directory"""
    system = platform.system()
    venv_names = ['.venv', 'venv', 'env']
    
    for venv_name in venv_names:
        if system == 'Windows':
            python_path = project_dir / venv_name / 'Scripts' / 'python.exe'
        else:
            python_path = project_dir / venv_name / 'bin' / 'python'
        
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
        # For workspace config, try to use relative path if Python is in project
        try:
            rel_path = current_python.relative_to(project_dir)
            # Convert to forward slashes for cross-platform compatibility
            return './' + str(rel_path).replace('\\', '/')
        except ValueError:
            # Python is not in project directory, try to find a venv
            venv_python = find_venv_python(project_dir)
            if venv_python:
                try:
                    rel_path = venv_python.relative_to(project_dir)
                    return './' + str(rel_path).replace('\\', '/')
                except ValueError:
                    pass
            # Fall back to absolute path
            return str(current_python)
    else:
        # Use absolute path for user configuration
        return str(current_python)


def setup_mcp_config(config_type: str, variant: str | None = None):
    """
    Set up the MCP configuration for Cursor.
    
    Args:
        config_type: Either 'user' or 'workspace'
        variant: Cursor variant ('Cursor' or 'Cursor Nightly'), only used for user config
    """
    print_color("Evo MCP Configuration Setup for Cursor", Colors.BLUE)
    print("=" * 30)
    print()
    
    # Get the project directory (parent of scripts folder)
    script_dir = Path(__file__).parent.resolve()
    project_dir = script_dir.parent
    
    is_workspace = config_type == 'workspace'
    
    if is_workspace:
        # Workspace configuration
        config_dir = Path('.cursor')
        config_file = config_dir / 'mcp.json'
        print_color("Using workspace folder configuration", Colors.GREEN)
    else:
        # User configuration
        config_dir = get_config_dir(variant)
        
        if not config_dir:
            cursor_name = variant if variant else "Cursor"
            print_color(f"✗ Could not find {cursor_name} installation directory", Colors.RED)
            sys.exit(1)
        
        config_file = config_dir / 'mcp.json'
        cursor_name = variant if variant else "Cursor"
        print_color(f"Using user configuration for {cursor_name}", Colors.GREEN)
    
    print(f"Configuration file: {config_file}")
    print()
    
    # Get paths
    python_exe = get_python_executable(project_dir, is_workspace)
    if is_workspace:
        mcp_script = './src/mcp_tools.py'
    else:
        mcp_script = str(project_dir / 'src' / 'mcp_tools.py')
    
    # Create directory if it doesn't exist
    config_dir.mkdir(parents=True, exist_ok=True)
    
    # Read or create settings JSON
    if config_file.exists():
        try:
            with open(config_file, 'r', encoding='utf-8') as f:
                settings = json.load(f)
        except json.JSONDecodeError as e:
            print_color(f"✗ Invalid JSON in existing config file: {e}", Colors.RED)
            print(f"Please fix the syntax error in: {config_file}")
            sys.exit(1)
    else:
        settings = {}
    
    # Ensure mcpServers exists (Cursor uses mcpServers key)
    if 'mcpServers' not in settings:
        settings['mcpServers'] = {}
    
    # Add or update the evo-mcp server configuration
    settings['mcpServers']['evo-mcp'] = {
        "command": python_exe,
        "args": [mcp_script]
    }
    
    # Write the updated settings to file
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2)
        
        print_color("✓ Successfully added Evo MCP configuration", Colors.GREEN)
        print()
        print("Configuration details:")
        print(f"  Command: {python_exe}")
        print(f"  Script: {mcp_script}")
        print()
        print("Next steps:")
        print("Restart Cursor or reload the window")
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
    print_color("Evo MCP Configuration Setup for Cursor", Colors.BLUE)
    print("=" * 30)
    print()
    
    # Use stable Cursor version
    variant = 'Cursor'
    
    # Ask where to add configuration
    try:
        while True:
            print("Where would you like to add the MCP server configuration?")
            print("1. User configuration (default)")
            print("2. Workspace folder configuration")
            print()
            
            choice = input("Enter your choice [1-2] (default: 1): ").strip()
            if not choice:
                choice = '1'
            
            if choice in ['1', '2']:
                break
            
            print_color("Invalid choice. Please enter 1 or 2.", Colors.RED)
            print()
        
        config_type = 'user' if choice == '1' else 'workspace'
        print()
        setup_mcp_config(config_type, variant if config_type == 'user' else None)
        
    except KeyboardInterrupt:
        print()
        print_color("Setup cancelled by user", Colors.RED)
        sys.exit(1)


if __name__ == '__main__':
    main()
