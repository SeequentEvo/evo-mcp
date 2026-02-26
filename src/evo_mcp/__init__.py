# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Evo Model Context Protocol (MCP) Server Package

This package provides tools for interacting with the Evo platform,
including workspace management, object operations, and data transfer capabilities.
"""

from .context import EvoContext, ensure_initialized
import importlib.metadata
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib

try:
    # Get the distribution package name associated with the current module (__name__)
    # __name__ will be 'evo_mcp' when this file is imported.
    # packages_distributions() returns a dict like {'evo_mcp': ['evo-mcp']}
    __dist_name__ = importlib.metadata.packages_distributions()[__name__][0]
    
    # Now use the dynamically found distribution name to get the version
    __version__ = importlib.metadata.version(__dist_name__)

except (KeyError, IndexError, importlib.metadata.PackageNotFoundError):
    # Fallback for running from source without an editable install.
    # Tries to read directly from pyproject.toml.
    __dist_name__ = "evo-mcp-local"
    __version__ = "0.0.0-local"
    try:
        pyproject_path = Path(__file__).parent.parent.parent / "pyproject.toml"
        if pyproject_path.exists():
            with open(pyproject_path, "rb") as f:
                pyproject_data = tomllib.load(f)
            __dist_name__ = pyproject_data.get("project", {}).get("name", __dist_name__)
            __version__ = pyproject_data.get("project", {}).get("version", __version__)
    except (ImportError, FileNotFoundError, Exception):
        # If tomllib is not available or file is not found, use hardcoded defaults.
        pass

__all__ = ['EvoContext', 'ensure_initialized', "__version__", "__dist_name__"]
