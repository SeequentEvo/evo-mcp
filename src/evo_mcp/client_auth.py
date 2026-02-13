# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

import json as _json
import logging
import os

from evo.oauth import EvoScopes
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)


def create_auth_provider(base_url: str):
    """Create an OIDCProxy auth provider for HTTP transport.

    Uses Bentley IMS as the upstream OIDC provider. The proxy handles
    Dynamic Client Registration for MCP clients and proxies the OAuth
    authorization code flow to Bentley IMS.

    In HTTP mode, the MCP server itself receives the OAuth callback from IMS.
    The upstream callback URL is ``{base_url}/auth/callback`` — this must be
    registered as an allowed redirect URI in the iTwin/IMS application.

    Note: This is NOT the same as EVO_REDIRECT_URL, which is only used in
    non-delegated mode where the evo SDK runs its own local callback server.

    Args:
        base_url: The public base URL of this server (e.g. "http://localhost:5001").
    """

    client_id = os.getenv("EVO_CLIENT_ID")
    if not client_id:
        raise ValueError(
            "EVO_CLIENT_ID environment variable is required for authentication. "
            "Register an application at the iTwin Developer Portal and set EVO_CLIENT_ID."
        )
    issuer_url = os.getenv("ISSUER_URL", "https://ims.bentley.com")
    config_url = f"{issuer_url}/.well-known/openid-configuration"

    # In HTTP mode the MCP server receives the OAuth callback — not the SDK's
    # local server.  Use the OIDCProxy default path (/auth/callback) so the
    # redirect URI is deterministic: {base_url}/auth/callback.

    # Bentley IMS native/SPA apps are public clients (no client secret).
    # The proxy authenticates upstream using PKCE only.
    evo_scopes = str(EvoScopes.all_evo)

    return OIDCProxy(
        config_url=config_url,
        client_id=client_id,
        client_secret="unused",
        token_endpoint_auth_method="none",
        base_url=base_url,
        require_authorization_consent=False,
        extra_authorize_params={"scope": evo_scopes},
        # MCP clients send an RFC 8707 resource indicator (the MCP server URL).
        # Do not forward it to Bentley IMS — IMS has its own resource model and
        # rejects unknown resource URLs with invalid_target.
        # See: https://github.com/PrefectHQ/fastmcp/issues/3939
        forward_resource=False,
    )


# ---------------------------------------------------------------------------
# ASGI Middleware: patch OAuth metadata for public MCP clients
# ---------------------------------------------------------------------------
# FastMCP's built-in OAuth metadata endpoint only advertises
# ["client_secret_post", "client_secret_basic"] in
# token_endpoint_auth_methods_supported.  However, public MCP clients
# (VS Code Copilot, Claude Code, etc.) register via DCR with
# token_endpoint_auth_method: "none" because they don't possess a client
# secret.  Without "none" in the metadata, compliant clients may refuse to
# authenticate.
#
# This middleware intercepts GET /.well-known/oauth-authorization-server
# responses and appends "none" to the list.
#
# Remove this middleware once the MCP Python SDK includes "none" natively
# in build_metadata(). Fix merged but not yet released in mcp>=1.27.0.
# Upstream: https://github.com/modelcontextprotocol/python-sdk/issues/2260
# ---------------------------------------------------------------------------


class AuthMetadataPatchMiddleware:
    """ASGI middleware that patches OAuth metadata to include ``"none"``
    in ``token_endpoint_auth_methods_supported``.

    Required for public MCP clients (VS Code, Claude Code) that use
    ``token_endpoint_auth_method: "none"`` during Dynamic Client Registration.
    FastMCP only advertises ``["client_secret_post", "client_secret_basic"]``.

    **When to remove:** once the ``mcp`` SDK (>=1.26.0 successor) includes
    ``"none"`` in ``build_metadata()``. Tracked in
    `python-sdk#2260 <https://github.com/modelcontextprotocol/python-sdk/issues/2260>`_.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "?")
        logger.debug("[req] %s %s", method, path)

        if not path.startswith("/.well-known/oauth-authorization-server"):
            await self.app(scope, receive, send)
            return

        # Capture response body, patch token_endpoint_auth_methods_supported
        response_body = bytearray()
        response_started = False
        original_headers: list = []
        original_status = 200

        async def capture_send(message):
            nonlocal response_started, original_headers, original_status
            if message["type"] == "http.response.start":
                response_started = True
                original_status = message.get("status", 200)
                original_headers = list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                response_body.extend(message.get("body", b""))

        await self.app(scope, receive, capture_send)

        try:
            data = _json.loads(bytes(response_body))
            methods = data.get("token_endpoint_auth_methods_supported", [])
            if "none" not in methods:
                methods.append("none")
                data["token_endpoint_auth_methods_supported"] = methods
            patched = _json.dumps(data).encode()

            new_headers = [(k, v) for k, v in original_headers if k != b"content-length"]
            new_headers.append((b"content-length", str(len(patched)).encode()))

            await send(
                {
                    "type": "http.response.start",
                    "status": original_status,
                    "headers": new_headers,
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": patched,
                }
            )
            logger.debug("Patched auth metadata: added 'none' to token_endpoint_auth_methods_supported")
        except Exception:
            await send(
                {
                    "type": "http.response.start",
                    "status": original_status,
                    "headers": original_headers,
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": bytes(response_body),
                }
            )
