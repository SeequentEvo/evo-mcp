# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import os
from uuid import UUID

import pytest

from evo_mcp.context import ensure_initialized, evo_context

_REQUIRED_ENV_VARS = [
    "EVO_CLIENT_ID",
    "EVO_CLIENT_SECRET",
    "EVO_DISCOVERY_URL",
]


def _required_uuid_env(var_name: str) -> UUID:
    raw_value = os.getenv(var_name, "").strip()
    if not raw_value:
        pytest.skip(f"Set {var_name} to run this live integration test deterministically")

    try:
        return UUID(raw_value)
    except ValueError as exc:
        pytest.fail(f"{var_name} must be a valid UUID, got {raw_value!r}: {exc}")


def require_live_env() -> None:
    if os.getenv("RUN_EVO_LIVE_TESTS") != "1":
        pytest.skip("Set RUN_EVO_LIVE_TESTS=1 to run live Evo integration tests")

    auth_method = os.getenv("AUTH_METHOD", "client_credentials").strip().lower() or "client_credentials"
    if auth_method != "client_credentials":
        pytest.fail("Live integration tests require AUTH_METHOD=client_credentials")

    # Live integration tests should not reuse a previously cached user token.
    os.environ["AUTH_METHOD"] = "client_credentials"
    os.environ["EVO_DISABLE_TOKEN_CACHE"] = "1"

    missing = [name for name in _REQUIRED_ENV_VARS if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing required environment variables: {', '.join(missing)}")


async def ensure_deterministic_live_context() -> None:
    require_live_env()
    await ensure_initialized()

    target_instance_id = _required_uuid_env("EVO_TEST_INSTANCE_ID")
    if evo_context.org_id == target_instance_id:
        return

    instances = await evo_context.discovery_client.list_organizations()
    for instance in instances:
        if instance.id == target_instance_id:
            await evo_context.switch_instance(instance.id, instance.hubs[0].url)
            return

    pytest.fail(f"Configured EVO_TEST_INSTANCE_ID {target_instance_id} was not found in discovery results")


async def get_required_workspace():
    await ensure_deterministic_live_context()

    workspace_id = _required_uuid_env("EVO_TEST_WORKSPACE_ID")
    try:
        return await evo_context.workspace_client.get_workspace(workspace_id)
    except Exception as exc:
        pytest.fail(f"Configured EVO_TEST_WORKSPACE_ID {workspace_id} is not accessible: {exc}")


def get_required_object_path() -> str:
    object_path = os.getenv("EVO_TEST_OBJECT_PATH", "").strip()
    if not object_path:
        pytest.skip("Set EVO_TEST_OBJECT_PATH to run the live get_object_by_path integration test deterministically")
    return object_path
