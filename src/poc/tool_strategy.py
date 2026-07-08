# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Tool-exposure strategy factory for Evo MCP.

A single place that decides *how* an LLM sees and reaches the tool catalog:

  - ``none``        — the full catalog is listed upfront (today's behavior).
  - ``tool-search`` — the catalog is hidden behind ``search_tools`` / ``call_tool``
                      (FastMCP Tool Search transform).
  - ``code-mode``   — the catalog is hidden behind ``search`` / ``get_schema`` /
                      ``execute``; the LLM writes Python that chains tool calls in a
                      sandbox (FastMCP Code Mode transform).

The strategy is selected with the ``MCP_TOOL_STRATEGY`` environment variable and
applied to an already-populated :class:`FastMCP` server with :func:`apply_strategy`.

This module is intentionally free of Evo-specific imports so it can wrap both the
real server (``src/mcp_tools.py``) and the PoC demo server.
"""

from __future__ import annotations

import logging
import os
from enum import Enum

from fastmcp import FastMCP

logger = logging.getLogger(__name__)

STRATEGY_ENV = "MCP_TOOL_STRATEGY"
SEARCH_ENGINE_ENV = "MCP_SEARCH_ENGINE"


class ToolStrategy(str, Enum):
    """How the tool catalog is exposed to the LLM."""

    NONE = "none"
    TOOL_SEARCH = "tool-search"
    CODE_MODE = "code-mode"


class SearchEngine(str, Enum):
    """Ranking engine used by the Tool Search strategy."""

    BM25 = "bm25"
    REGEX = "regex"


def strategy_from_env() -> ToolStrategy:
    """Read the desired strategy from ``MCP_TOOL_STRATEGY`` (default ``none``)."""
    raw = os.getenv(STRATEGY_ENV, ToolStrategy.NONE.value).strip().lower()
    try:
        return ToolStrategy(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; valid values are %s. Defaulting to 'none'.",
            STRATEGY_ENV,
            raw,
            [s.value for s in ToolStrategy],
        )
        return ToolStrategy.NONE


def search_engine_from_env() -> SearchEngine:
    """Read the Tool Search engine from ``MCP_SEARCH_ENGINE`` (default ``bm25``)."""
    raw = os.getenv(SEARCH_ENGINE_ENV, SearchEngine.BM25.value).strip().lower()
    try:
        return SearchEngine(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%r; valid values are %s. Defaulting to 'bm25'.",
            SEARCH_ENGINE_ENV,
            raw,
            [e.value for e in SearchEngine],
        )
        return SearchEngine.BM25


def _build_tool_search_transform(
    engine: SearchEngine,
    *,
    max_results: int,
    always_visible: list[str] | None,
):
    """Construct a Tool Search transform for the requested engine."""
    from fastmcp.server.transforms.search import (
        BM25SearchTransform,
        RegexSearchTransform,
    )

    cls = BM25SearchTransform if engine is SearchEngine.BM25 else RegexSearchTransform
    return cls(max_results=max_results, always_visible=always_visible or None)


def _build_code_mode_transform():
    """Construct a Code Mode transform with the default staged discovery + sandbox.

    Importing here keeps the ``fastmcp[code-mode]`` extra optional: the import only
    happens when the code-mode strategy is actually selected.
    """
    from fastmcp.experimental.transforms.code_mode import CodeMode

    return CodeMode()


def apply_strategy(
    mcp: FastMCP,
    strategy: ToolStrategy | None = None,
    *,
    search_engine: SearchEngine | None = None,
    max_results: int = 5,
    always_visible: list[str] | None = None,
) -> ToolStrategy:
    """Apply a tool-exposure *strategy* to an already-populated *mcp* server.

    Call this AFTER all tools have been registered, because the search index and
    the code-mode catalog are built from the current tool set.

    Args:
        mcp: A FastMCP server that already has its tools registered.
        strategy: The strategy to apply. Defaults to :func:`strategy_from_env`.
        search_engine: Engine for the tool-search strategy. Defaults to
            :func:`search_engine_from_env`.
        max_results: Max tools returned per ``search_tools`` call (tool-search only).
        always_visible: Tool names to keep pinned in ``list_tools`` regardless of
            strategy (e.g. a ``help`` or ``select_instance`` tool).

    Returns:
        The :class:`ToolStrategy` that was applied.
    """
    strategy = strategy or strategy_from_env()

    if strategy is ToolStrategy.NONE:
        logger.info("Tool strategy: none (full catalog listed upfront).")
        return strategy

    if strategy is ToolStrategy.TOOL_SEARCH:
        engine = search_engine or search_engine_from_env()
        transform = _build_tool_search_transform(engine, max_results=max_results, always_visible=always_visible)
        mcp.add_transform(transform)
        logger.info("Tool strategy: tool-search (engine=%s).", engine.value)
        return strategy

    if strategy is ToolStrategy.CODE_MODE:
        mcp.add_transform(_build_code_mode_transform())
        logger.info("Tool strategy: code-mode (staged discovery + sandbox).")
        return strategy

    return ToolStrategy.NONE  # pragma: no cover - defensive
