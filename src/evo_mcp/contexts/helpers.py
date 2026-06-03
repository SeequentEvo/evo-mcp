# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

import hashlib

import jwt as pyjwt
from fastmcp.server.dependencies import get_access_token, get_http_request


def get_user_id_from_token(token: str) -> str:
    """Extract user identifier from the IMS JWT ``sub`` claim.

    Raises ``RuntimeError`` if the token has no valid ``sub`` claim.
    """
    claims = pyjwt.decode(token, options={"verify_signature": False})
    sub = claims.get("sub")
    if isinstance(sub, str) and sub:
        return sub
    raise RuntimeError("JWT is missing a valid 'sub' claim")


def get_client_session_upstream_access_token() -> str:
    """Get the upstream access token for the current MCP client session.

    This is used as part of the composite key for session identification and
    also to detect token changes on each request for context re-initialization.
    """
    token_obj = get_access_token()
    if not token_obj or not token_obj.token:
        raise RuntimeError("No FastMCP access token available in delegated auth mode")
    return token_obj.token


def get_client_session_id() -> str:
    """Return a stable identifier for the current MCP client session.

    Combines the ``mcp-session-id`` HTTP header (or token-hash fallback)
    with the user's identity (``sub`` claim from the IMS JWT).  This
    composite key prevents session-ID spoofing: even if an attacker
    forges the ``mcp-session-id`` header, the resulting key won't match
    another user's context because the ``sub`` claim differs.
    """
    upstream_access_token = get_client_session_upstream_access_token()
    user_id = get_user_id_from_token(upstream_access_token)

    try:
        request = get_http_request()
        session_id = request.headers.get("mcp-session-id")
        if session_id:
            composite = f"{user_id}:{session_id}"
        else:
            # Fallback: (user_id + token) hash (no state persistence across refreshes)
            composite = f"{user_id}:{upstream_access_token}"
    except Exception:
        # Fallback: (user_id + token) hash (no state persistence across refreshes)
        composite = f"{user_id}:{upstream_access_token}"

    return hashlib.sha256(composite.encode()).hexdigest()[:32]
