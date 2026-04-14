# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

import os
from urllib.parse import urlparse

from evo.oauth import EvoScopes
from fastmcp.server.auth.oidc_proxy import OIDCProxy

def create_auth_provider(base_url: str):
    """Create an OIDCProxy auth provider for HTTP transport.

    Uses Bentley IMS as the upstream OIDC provider. The proxy handles
    Dynamic Client Registration for MCP clients and proxies the OAuth
    authorization code flow to Bentley IMS.

    The upstream callback URL (where IMS redirects after login) must be
    registered as an allowed redirect URI in the IMS application.
    It is NOT the same as EVO_REDIRECT_URL, which is only used in STDIO mode.

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

    # Derive the callback path from EVO_REDIRECT_URL so the same URL registered
    # in the IMS application works for both STDIO and HTTP+OIDCProxy modes.
    # e.g. http://localhost:3000/signin-callback → /signin-callback
    # Falls back to /auth/callback if EVO_REDIRECT_URL is not set.
    redirect_url = os.getenv("EVO_REDIRECT_URL", "")
    if redirect_url:
        parsed_url = urlparse(redirect_url)
        redirect_path = parsed_url.path or "/auth/callback"
    else:
        redirect_path = "/auth/callback"

    # Bentley IMS native/SPA apps are public clients (no client secret).
    # The proxy authenticates upstream using PKCE only.
    evo_scopes = f"openid {EvoScopes.all_evo}"

    _apply_loopback_redirect_patch()

    return OIDCProxy(
        config_url=config_url,
        client_id=client_id,
        client_secret="unused",
        token_endpoint_auth_method="none",
        base_url=base_url,
        redirect_path=redirect_path,
        require_authorization_consent=False,
        extra_authorize_params={"scope": evo_scopes},
        # MCP clients send an RFC 8707 resource indicator (the MCP server URL).
        # Do not forward it to Bentley IMS — IMS has its own resource model and
        # rejects unknown resource URLs with invalid_target.
        # See: https://github.com/PrefectHQ/fastmcp/issues/3939
        forward_resource=False,
    )





# ---------------------------------------------------------------------------
# Monkey-patch: RFC 8252 §7.3 loopback redirect URI port matching
# ---------------------------------------------------------------------------
# FastMCP's redirect_validation treats "http://localhost/callback" (no port) as
# port 80, which rejects dynamic-port loopback URIs like
# "http://localhost:56053/callback".  Per RFC 8252 §7.3 the authorization
# server MUST allow any port for loopback redirect URIs.
#
# Claude Code's CIMD declares redirect_uris without a port, so we patch the
# matching function to treat a missing port on loopback patterns as a wildcard.
# This patch can be removed once FastMCP ships a fix upstream.
# ---------------------------------------------------------------------------
_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1"}
_loopback_patch_applied = False


def _apply_loopback_redirect_patch() -> None:
    """Patch fastmcp redirect-URI matching for RFC 8252 loopback compliance.

    Safe to call multiple times — the patch is only applied once.
    """
    global _loopback_patch_applied
    if _loopback_patch_applied:
        return
    _loopback_patch_applied = True

    from fastmcp.server.auth import redirect_validation as _rv
    from fastmcp.server.auth.oauth_proxy import models as _models

    _original_match_port = _rv._match_port

    def _patched_match_port(
        uri_port: "str | None",
        pattern_port: "str | None",
        uri_scheme: str,
        *,
        _pattern_host: "str | None" = None,
    ) -> bool:
        # RFC 8252 §7.3: loopback pattern with no explicit port → any port
        if (
            pattern_port is None
            and _pattern_host is not None
            and _pattern_host.lower() in _LOOPBACK_HOSTS
        ):
            return True
        return _original_match_port(uri_port, pattern_port, uri_scheme)

    _original_matches = _rv.matches_allowed_pattern

    def _patched_matches_allowed_pattern(uri: str, pattern: str) -> bool:
        from urllib.parse import urlparse as _urlparse

        try:
            uri_parsed = _urlparse(uri)
            pattern_parsed = _urlparse(pattern)
        except ValueError:
            return _original_matches(uri, pattern)

        if uri_parsed.username is not None or uri_parsed.password is not None:
            return False

        if uri_parsed.scheme.lower() != pattern_parsed.scheme.lower():
            return False

        uri_host, uri_port = _rv._parse_host_port(uri_parsed.netloc)
        pattern_host, pattern_port = _rv._parse_host_port(pattern_parsed.netloc)

        if not _rv._match_host(uri_host, pattern_host):
            return False

        if not _patched_match_port(
            uri_port, pattern_port, uri_parsed.scheme.lower(),
            _pattern_host=pattern_host,
        ):
            return False

        return _rv._match_path(uri_parsed.path, pattern_parsed.path)

    # Patch both the module-level function and the reference inside models.py
    _rv.matches_allowed_pattern = _patched_matches_allowed_pattern
    _models.matches_allowed_pattern = _patched_matches_allowed_pattern
