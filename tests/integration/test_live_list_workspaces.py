# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import pytest

from evo_mcp.context import evo_context
from tests.integration.live_test_support import ensure_deterministic_live_context


@pytest.mark.integration
async def test_live_list_workspaces_read_only():
    """Given live-test env is enabled, when listing workspaces, then a valid read-only response is returned.

    This test is skipped by default and only runs when explicitly enabled with
    RUN_EVO_LIVE_TESTS=1, auth env vars, and a deterministic instance selection.
    """

    await ensure_deterministic_live_context()

    assert evo_context.workspace_client is not None

    page = await evo_context.workspace_client.list_workspaces(limit=5)
    items = page.items()

    assert isinstance(items, list)
    for workspace in items:
        assert workspace.id is not None
        assert workspace.display_name
