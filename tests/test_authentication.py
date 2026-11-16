# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""OAuth metadata and Dynamic Client Registration regression tests."""

from __future__ import annotations

import importlib
import os
import sys
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import pytest_asyncio
from evo.oauth import EvoScopes
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration, OIDCProxy
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response

from evo_mcp.client_auth import SilentAuthOIDCProxy, create_auth_provider

_BASE_URL = "https://mcp.example"
_ALLOWED_REDIRECT_URI = "https://allowed.example/callback"


def _ims_configuration() -> OIDCConfiguration:
    return OIDCConfiguration(
        issuer="https://ims.example",
        authorization_endpoint="https://ims.example/authorize",
        token_endpoint="https://ims.example/token",
        jwks_uri="https://ims.example/jwks",
        response_types_supported=["code"],
        subject_types_supported=["public"],
        id_token_signing_alg_values_supported=["RS256"],
    )


@pytest.fixture
def auth_provider_factory():
    def create(**environment: str) -> SilentAuthOIDCProxy:
        with (
            patch.dict(os.environ, {"EVO_CLIENT_ID": "evo-client"} | environment),
            patch.object(
                SilentAuthOIDCProxy,
                "get_oidc_configuration",
                return_value=_ims_configuration(),
            ),
        ):
            return create_auth_provider(_BASE_URL)

    return create


@pytest.fixture
def auth_provider(auth_provider_factory) -> SilentAuthOIDCProxy:
    return auth_provider_factory()


@pytest_asyncio.fixture
async def oauth_client(auth_provider):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=Starlette(routes=auth_provider.get_routes())),
        base_url=_BASE_URL,
    ) as client:
        yield client


@pytest_asyncio.fixture
async def restricted_oauth_client(auth_provider_factory):
    provider = auth_provider_factory(MCP_ALLOWED_CLIENT_REDIRECT_URIS=_ALLOWED_REDIRECT_URI)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=Starlette(routes=provider.get_routes())),
        base_url=_BASE_URL,
    ) as client:
        yield client


@pytest.fixture
def delegated_server():
    original_module = sys.modules.pop("mcp_tools", None)
    with (
        patch.dict(
            os.environ,
            {
                "MCP_TRANSPORT": "http",
                "CLIENT_DELEGATED_AUTH": "true",
                "EVO_CLIENT_ID": "evo-client",
                "MCP_PUBLIC_BASE_URL": _BASE_URL,
            },
        ),
        patch.object(
            SilentAuthOIDCProxy,
            "get_oidc_configuration",
            return_value=_ims_configuration(),
        ),
    ):
        module = importlib.import_module("mcp_tools")
    try:
        yield module
    finally:
        sys.modules.pop("mcp_tools", None)
        if original_module is not None:
            sys.modules["mcp_tools"] = original_module


@pytest_asyncio.fixture
async def delegated_server_client(delegated_server):
    app = delegated_server.mcp.http_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=_BASE_URL,
    ) as client:
        yield client


def test_auth_provider_uses_evo_public_client_settings(auth_provider):
    assert auth_provider._forward_resource is False
    assert auth_provider._token_endpoint_auth_method == "none"
    assert auth_provider._require_authorization_consent == "remember"
    assert auth_provider._redirect_path == "/signin-callback"
    assert auth_provider._extra_authorize_params == {
        "scope": EvoScopes.all_evo,
        "prompt": "none",
    }


def test_auth_provider_uses_custom_ims_callback_path(auth_provider_factory):
    provider = auth_provider_factory(OIDCPROXY_REDIRECT_PATH="/oauth/ims-callback")

    assert provider._redirect_path == "/oauth/ims-callback"
    assert "/oauth/ims-callback" in {route.path for route in provider.get_routes()}


def test_auth_provider_requires_an_evo_client_id(auth_provider_factory):
    with pytest.raises(ValueError, match="EVO_CLIENT_ID environment variable is required"):
        auth_provider_factory(EVO_CLIENT_ID="")


@pytest.mark.asyncio
async def test_oauth_metadata_advertises_public_client_authentication(oauth_client):
    response = await oauth_client.get("/.well-known/oauth-authorization-server")

    response.raise_for_status()
    metadata = response.json()
    supported_auth_methods = metadata["token_endpoint_auth_methods_supported"]
    assert isinstance(supported_auth_methods, list)
    assert "none" in supported_auth_methods
    assert metadata["registration_endpoint"] == f"{_BASE_URL}/register"


@pytest.mark.asyncio
async def test_dynamic_client_registration_accepts_a_public_client(oauth_client):
    response = await oauth_client.post(
        "/register",
        json={
            "redirect_uris": ["http://localhost/callback"],
            "token_endpoint_auth_method": "none",
        },
    )

    response.raise_for_status()
    registered_client = response.json()
    assert registered_client["token_endpoint_auth_method"] == "none"
    assert registered_client["redirect_uris"] == ["http://localhost/callback"]
    assert registered_client["client_id"]


@pytest.mark.asyncio
async def test_dynamic_client_registration_enforces_redirect_allowlist(restricted_oauth_client):
    rejected = await restricted_oauth_client.post(
        "/register",
        json={
            "redirect_uris": ["https://untrusted.example/callback"],
            "token_endpoint_auth_method": "none",
        },
    )
    accepted = await restricted_oauth_client.post(
        "/register",
        json={
            "redirect_uris": [_ALLOWED_REDIRECT_URI],
            "token_endpoint_auth_method": "none",
        },
    )

    assert rejected.status_code == 400
    assert accepted.status_code == 201


@pytest.mark.asyncio
async def test_silent_ims_login_retries_once_without_prompt(auth_provider):
    transaction = MagicMock()
    transaction.model_dump.return_value = {"client_id": "mcp-client"}
    auth_provider._transaction_store.get = AsyncMock(return_value=transaction)
    auth_provider._build_upstream_authorize_url = MagicMock(
        return_value="https://ims.example/authorize?prompt=none&state=transaction-1"
    )
    callback = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/signin-callback",
            "query_string": b"error=login_required&state=transaction-1",
            "headers": [],
        }
    )
    fallback_response = Response(status_code=418)

    with patch.object(
        OIDCProxy,
        "_handle_idp_callback",
        new=AsyncMock(return_value=fallback_response),
    ) as upstream_callback:
        retry = await auth_provider._handle_idp_callback(callback)
        repeated_failure = await auth_provider._handle_idp_callback(callback)

    assert retry.status_code == 302
    assert "prompt" not in parse_qs(urlsplit(retry.headers["location"]).query)
    assert repeated_failure is fallback_response
    upstream_callback.assert_awaited_once_with(callback)


@pytest.mark.asyncio
async def test_delegated_server_wires_auth_provider_and_challenges_requests(
    delegated_server,
    delegated_server_client,
):
    assert delegated_server.CLIENT_DELEGATED_AUTH is True
    assert delegated_server.auth_provider is not None

    response = await delegated_server_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "1.0"},
            },
        },
    )

    assert response.status_code == 401
    assert response.headers["www-authenticate"].endswith('/.well-known/oauth-protected-resource/mcp"')
