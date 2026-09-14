# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

import logging
import os
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from cachetools import TTLCache
from evo.oauth import EvoScopes
from fastmcp.server.auth.oidc_proxy import OIDCProxy
from starlette.requests import Request
from starlette.responses import RedirectResponse

logger = logging.getLogger(__name__)
_SILENT_AUTH_ERRORS = frozenset(
    {"account_selection_required", "consent_required", "interaction_required", "login_required"}
)
_AUTH_TRANSACTION_TTL_SECONDS = 15 * 60
_ALLOWED_CLIENT_REDIRECT_URIS_ENV = "MCP_ALLOWED_CLIENT_REDIRECT_URIS"


class SilentAuthOIDCProxy(OIDCProxy):
    """Retry a failed silent IMS login once with normal browser interaction."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._interactive_fallback_transactions: TTLCache[str, bool] = TTLCache(
            maxsize=10_000,
            ttl=_AUTH_TRANSACTION_TTL_SECONDS,
        )

    async def _handle_idp_callback(self, request: Request):
        error = request.query_params.get("error")
        transaction_id = request.query_params.get("state")
        if error not in _SILENT_AUTH_ERRORS or not transaction_id:
            if transaction_id:
                self._interactive_fallback_transactions.pop(transaction_id, None)
            return await super()._handle_idp_callback(request)

        if transaction_id in self._interactive_fallback_transactions:
            return await super()._handle_idp_callback(request)

        transaction = await self._transaction_store.get(key=transaction_id)
        if transaction is None:
            return await super()._handle_idp_callback(request)

        self._interactive_fallback_transactions[transaction_id] = True
        interactive_url = _without_prompt(self._build_upstream_authorize_url(transaction_id, transaction.model_dump()))
        logger.info("Silent IMS authentication requires interaction, retrying with a normal browser login")
        return RedirectResponse(interactive_url, status_code=302)


def _without_prompt(url: str) -> str:
    """Remove the silent-auth prompt parameter for the interactive fallback."""
    parts = urlsplit(url)
    query = urlencode([(key, value) for key, value in parse_qsl(parts.query) if key != "prompt"])
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _allowed_client_redirect_uris() -> list[str] | None:
    value = os.getenv(_ALLOWED_CLIENT_REDIRECT_URIS_ENV, "").strip()
    if not value:
        return None
    return [uri.strip() for uri in value.split(",") if uri.strip()]


def create_auth_provider(base_url: str):
    """Create an OIDCProxy auth provider for HTTP transport.

    Uses Bentley IMS as the upstream OIDC provider. The proxy handles
    Dynamic Client Registration for MCP clients and proxies the OAuth
    authorization code flow to Bentley IMS.

    In delegated auth mode, the MCP server itself receives the OAuth callback from IMS.
    The callback path defaults to ``/signin-callback`` and can be overridden via
    the ``OIDCPROXY_REDIRECT_PATH`` env var.  The full redirect URI registered
    in your Bentley IMS application must be ``{MCP_PUBLIC_BASE_URL}{path}``.

    Args:
        base_url: The public base URL of this server (e.g. "http://localhost:5001").
    """

    client_id = os.getenv("EVO_CLIENT_ID")
    if not client_id:
        raise ValueError(
            "EVO_CLIENT_ID environment variable is required for authentication. "
            "Set the EVO_CLIENT_ID environment variable to the client ID of a native app you can create at the Seequent Developer Portal."
        )
    issuer_url = os.getenv("ISSUER_URL", "https://ims.bentley.com")
    config_url = f"{issuer_url}/.well-known/openid-configuration"

    # Allow overriding the redirect path for environments where the default
    # /signin-callback conflicts with other routes or IMS app registration.
    redirect_path = os.getenv("OIDCPROXY_REDIRECT_PATH", "/signin-callback")

    # Bentley IMS native/SPA apps are public clients (no client secret).
    # The proxy authenticates upstream using PKCE only.
    evo_scopes = str(EvoScopes.all_evo)

    return SilentAuthOIDCProxy(
        config_url=config_url,
        client_id=client_id,
        client_secret="unused",
        token_endpoint_auth_method="none",
        base_url=base_url,
        redirect_path=redirect_path,
        require_authorization_consent="remember",
        allowed_client_redirect_uris=_allowed_client_redirect_uris(),
        extra_authorize_params={"scope": evo_scopes, "prompt": "none"},
        # MCP clients send an RFC 8707 resource indicator (the MCP server URL).
        # Do not forward it to Bentley IMS — IMS has its own resource model and
        # rejects unknown resource URLs with invalid_target.
        # See: https://github.com/PrefectHQ/fastmcp/issues/3939
        forward_resource=False,
    )
