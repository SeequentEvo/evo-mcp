# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Tool-exposure strategy for the Evo MCP server.

A single place that decides *how* an LLM sees and reaches the tool catalog:

  - ``tool-search`` — the catalog is hidden behind ``search_tools`` / ``call_tool``
                      (FastMCP Tool Search transform). This is the **default**: it
                      keeps the per-request context small so the toolset can grow
                      without inflating what the model sees upfront.
  - ``none``        — the full catalog is listed upfront (the historical behavior).
                      Use this as an escape hatch for clients or evals that prefer a
                      flat catalog.

The strategy is applied to an already-populated :class:`FastMCP` server with
:func:`apply_strategy`. This module is intentionally environment-free: the caller
resolves the desired :class:`ToolStrategy` / :class:`SearchEngine` (e.g. from
environment variables) and passes them in explicitly.
"""

from __future__ import annotations

import logging
from enum import Enum

from fastmcp import FastMCP
from fastmcp.server.transforms.search import BM25SearchTransform, RegexSearchTransform

logger = logging.getLogger(__name__)


class ToolStrategy(str, Enum):
    """How the tool catalog is exposed to the LLM."""

    NONE = "none"
    TOOL_SEARCH = "tool-search"


class SearchEngine(str, Enum):
    """Ranking engine used by the Tool Search strategy."""

    BM25 = "bm25"
    REGEX = "regex"


def apply_strategy(
    mcp: FastMCP,
    strategy: ToolStrategy,
    *,
    search_engine: SearchEngine = SearchEngine.BM25,
    max_results: int = 5,
    always_visible: list[str] | None = None,
) -> ToolStrategy:
    """Apply a tool-exposure *strategy* to an already-populated *mcp* server.

    Call this AFTER all tools have been registered, because the search index is
    built from the current tool set.

    Args:
        mcp: A FastMCP server that already has its tools registered.
        strategy: The strategy to apply.
        search_engine: Engine for the tool-search strategy (ignored for ``none``).
        max_results: Max tools returned per ``search_tools`` call (tool-search only).
        always_visible: Tool names to keep pinned in ``list_tools`` regardless of
            strategy (e.g. bootstrap tools such as ``select_instance``).

    Returns:
        The :class:`ToolStrategy` that was applied.
    """
    if strategy is ToolStrategy.NONE:
        logger.info("Tool strategy: none (full catalog listed upfront).")
        return strategy

    if strategy is ToolStrategy.TOOL_SEARCH:
        transform_cls = BM25SearchTransform if search_engine is SearchEngine.BM25 else RegexSearchTransform
        mcp.add_transform(transform_cls(max_results=max_results, always_visible=always_visible or None))
        logger.info("Tool strategy: tool-search (engine=%s).", search_engine.value)
        return strategy

    raise ValueError(f"Unhandled tool strategy: {strategy!r}")
