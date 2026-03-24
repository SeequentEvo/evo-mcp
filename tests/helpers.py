# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from collections.abc import Callable


class FakeMCP:
    """Minimal MCP stub that records decorated tool functions."""

    def __init__(self) -> None:
        self.tools: dict[str, Callable] = {}

    def tool(self, *args, **kwargs):
        def decorator(fn: Callable) -> Callable:
            self.tools[fn.__name__] = fn
            return fn

        return decorator


class FakePage:
    """Small page-like container for SDK paging semantics."""

    def __init__(self, items: list):
        self._items = items

    def items(self):
        return self._items
