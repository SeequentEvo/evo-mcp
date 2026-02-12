# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Evo Model Context Protocol (MCP) Server Package

This package provides tools for interacting with the Evo platform,
including workspace management, object operations, and data transfer capabilities.
"""

from .context import EvoContext, ensure_initialized

__all__ = ['EvoContext', 'ensure_initialized']
