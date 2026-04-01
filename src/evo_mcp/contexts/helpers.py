import hashlib

import jwt as pyjwt
from fastmcp.server.dependencies import get_access_token, get_http_request

def get_user_id_from_token(token: str) -> str:
    """Extract user identifier from the IMS JWT ``sub`` claim.
    """
    claims = pyjwt.decode(token, options={"verify_signature": False})
    sub = claims.get("sub")
    if sub:
        return sub


def get_client_session_info() -> tuple[str, str]:
    """Return a stable identifier for the current MCP client session and the upstream access token.

    Combines the ``mcp-session-id`` HTTP header (or token-hash fallback)
    with the user's identity (``sub`` claim from the IMS JWT).  This
    composite key prevents session-ID spoofing: even if an attacker
    forges the ``mcp-session-id`` header, the resulting key won't match
    another user's context because the ``sub`` claim differs.
    """
    token_obj = get_access_token()
    if not token_obj or not token_obj.token:
        raise RuntimeError("No FastMCP access token available in delegated auth mode")

    user_id = get_user_id_from_token(token_obj.token)

    try:
        request = get_http_request()
        session_id = request.headers.get("mcp-session-id")
        if session_id:
            composite = f"{user_id}:{session_id}"
        else:
            raise RuntimeError("No mcp-session-id header found in request")
    except RuntimeError:
         # Fallback: (user_id + token) hash (no state persistence across refreshes)
         composite = f"{user_id}:{token_obj.token}"
    finally:
        return hashlib.sha256(composite.encode()).hexdigest()[:32], token_obj.token
