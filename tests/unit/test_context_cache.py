# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

from evo_mcp.context import EvoContext


pytestmark = pytest.mark.unit


def _write_token(path, token: str) -> None:
    path.write_text(json.dumps({"access_token": token}), encoding="utf-8")


def test_save_and_load_variables_round_trip(tmp_path):
    """Given cached context variables, when reloaded, then values round-trip correctly."""
    ctx = EvoContext()
    ctx.cache_path = tmp_path

    org_id = uuid4()
    hub_url = "https://hub.example"
    ctx.org_id = org_id
    ctx.hub_url = hub_url

    ctx.save_variables_to_cache()

    fresh = EvoContext()
    fresh.cache_path = tmp_path
    fresh.load_variables_from_cache()

    assert fresh.org_id == org_id
    assert fresh.hub_url == hub_url


def test_get_access_token_from_cache_valid_returns_token(tmp_path):
    """Given a valid cached JWT, when read from cache, then the token is returned."""
    ctx = EvoContext()
    ctx.cache_path = tmp_path

    valid_exp = datetime.now(timezone.utc) + timedelta(minutes=30)
    token = jwt.encode(
        {"sub": "user", "exp": valid_exp},
        key="this-is-a-safely-long-test-key-123456",
        algorithm="HS256",
    )
    _write_token(tmp_path / "evo_token_cache.json", token)

    assert ctx.get_access_token_from_cache() == token


def test_get_access_token_from_cache_expired_returns_none(tmp_path):
    """Given an expired cached JWT, when read from cache, then None is returned."""
    ctx = EvoContext()
    ctx.cache_path = tmp_path

    expired_exp = datetime.now(timezone.utc) - timedelta(minutes=30)
    token = jwt.encode(
        {"sub": "user", "exp": expired_exp},
        key="this-is-a-safely-long-test-key-123456",
        algorithm="HS256",
    )
    _write_token(tmp_path / "evo_token_cache.json", token)

    assert ctx.get_access_token_from_cache() is None
