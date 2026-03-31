# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Context entrypoint for Evo MCP tools.

Re-exports the context classes from ``evo_mcp.contexts`` and provides the
public ``get_evo_context()`` function that every tool calls.

See ``evo_mcp/contexts/`` for the class implementations:
  - base.py       — EvoContextBase (ABC)
  - managed.py    — ManagedAuthContext  (CLIENT_DELEGATED_AUTH=false)
  - delegated.py  — DelegatedAuthContext (CLIENT_DELEGATED_AUTH=true)
"""

import hashlib
import logging
import os
from pathlib import Path

from cachetools import TTLCache
from dotenv import load_dotenv
from fastmcp.server.dependencies import get_access_token, get_http_request

from evo_mcp.contexts import EvoContextBase, ManagedAuthContext, DelegatedAuthContext

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if os.environ.get("DEBUG") == "1" else logging.INFO)
log_handler = logging.FileHandler("mcp_tools_debug.log")
log_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(log_handler)

# ---------------------------------------------------------------------------
# Module-level registry
# ---------------------------------------------------------------------------

delegated_mode: bool = False
managed_context: ManagedAuthContext = ManagedAuthContext()

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
delegated_contexts: TTLCache[str, DelegatedAuthContext] = TTLCache(
    maxsize=float("inf"), ttl=SESSION_TTL_SECONDS
)

CLIENT_DELEGATED_AUTH_ENV = os.getenv("CLIENT_DELEGATED_AUTH", "false").lower()
if CLIENT_DELEGATED_AUTH_ENV in ("true", "1", "yes"):
    delegated_mode = True
    logger.info("Using client-delegated authentication mode")
else:
    delegated_mode = False
    logger.info("Using managed authentication mode")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_client_session_id() -> str:
    """Return a stable identifier for the current MCP client session.

    Prefers the ``mcp-session-id`` HTTP header (set by Streamable HTTP
    transport).  Falls back to a hash of the access token if no session header is available.
    """
    try:
        request = get_http_request()
        session_id = request.headers.get("mcp-session-id")
        if session_id:
            return session_id
    except RuntimeError:
        pass  # no HTTP request available
    token_obj = get_access_token()
    if not token_obj:
        raise RuntimeError("No FastMCP access token available in delegated auth mode")
    return hashlib.sha256(token_obj.token.encode()).hexdigest()[:16]

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_evo_context() -> EvoContextBase:
    """Return an initialized context for the current request.

    In managed mode, returns the single shared ManagedAuthContext.
    In delegated mode, looks up (or creates) a DelegatedAuthContext
    keyed by the MCP session ID.  If the context already exists (i.e.
    the session is known), the access token is hot-swapped so that
    instance and workspace selection survive token refreshes.
    """
    if not delegated_mode:
        await managed_context.initialize()
        return managed_context

    token_obj = get_access_token()
    if not token_obj:
        raise RuntimeError("No FastMCP access token available in delegated auth mode")
    upstream_access_token = token_obj.token
    session_id = get_client_session_id()

    context = delegated_contexts.get(session_id)
    if context is not None:
        context.update_access_token(upstream_access_token)
        # Re-insert to reset TTL timer
        delegated_contexts[session_id] = context
        return context

    # New session
    context = DelegatedAuthContext(client_session_id=session_id, access_token=upstream_access_token)
    await context.initialize()
    delegated_contexts[session_id] = context
    logger.debug("Created new delegated context for session %s", session_id[:8])
    return context
