# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os

import pytest

from evo_mcp.context import ensure_initialized, evo_context


_REQUIRED_ENV_VARS = [
    "EVO_CLIENT_ID",
    "EVO_REDIRECT_URL",
    "EVO_DISCOVERY_URL",
]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_live_list_workspaces_read_only():
    """Given live-test env is enabled, when listing workspaces, then a valid read-only response is returned.

    This test is skipped by default and only runs when explicitly enabled with
    RUN_EVO_LIVE_TESTS=1 and required Evo auth environment variables.
    """

    if os.getenv("RUN_EVO_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_EVO_LIVE_TESTS=1 to run live Evo integration tests")

    missing = [name for name in _REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing required environment variables: {', '.join(missing)}")

    await ensure_initialized()

    assert evo_context.workspace_client is not None

    page = await evo_context.workspace_client.list_workspaces(limit=5)
    items = page.items()

    assert isinstance(items, list)
    for workspace in items:
        assert workspace.id is not None
        assert workspace.display_name
