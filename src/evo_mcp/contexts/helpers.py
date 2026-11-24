# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

import jwt as pyjwt
from fastmcp.server.dependencies import get_access_token


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

    This identifies the user owning a conversation and detects token changes
    on each request for context re-initialization.
    """
    token_obj = get_access_token()
    if not token_obj or not token_obj.token:
        raise RuntimeError("No FastMCP access token available in delegated auth mode")
    return token_obj.token
