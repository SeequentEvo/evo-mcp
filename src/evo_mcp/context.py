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

import asyncio
import logging
import os
import shutil
from pathlib import Path

from cachetools import TTLCache
from dotenv import load_dotenv

from evo_mcp.contexts import EvoContextBase, ManagedAuthContext, DelegatedAuthContext
from evo_mcp.contexts.helpers import get_client_session_info

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if os.environ.get("DEBUG") == "1" else logging.INFO)
log_handler = logging.FileHandler("mcp_tools_debug.log")
log_handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(log_handler)


delegated_mode: bool = False
managed_context: ManagedAuthContext = ManagedAuthContext()

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
delegated_contexts: TTLCache[str, DelegatedAuthContext] = TTLCache(
    maxsize=float("inf"), ttl=SESSION_TTL_SECONDS
)
session_locks: dict[str, asyncio.Lock] = {}

CLIENT_DELEGATED_AUTH_ENV = os.getenv("CLIENT_DELEGATED_AUTH", "false").lower()
if CLIENT_DELEGATED_AUTH_ENV in ("true", "1", "yes"):
    delegated_mode = True
    logger.info("Using client-delegated authentication mode")
else:
    delegated_mode = False
    logger.info("Using managed authentication mode")


async def get_evo_context() -> EvoContextBase:
    """Return an initialized context for the current request.

    In managed mode, returns the single shared ManagedAuthContext.
    In delegated mode, looks up (or creates) a DelegatedAuthContext
    keyed by the MCP session ID.  On every request the context is
    re-initialized with the current access token, rebuilding API clients
    cleanly while preserving instance selection via seeds.
    """
    if not delegated_mode:
        await managed_context.initialize()
        return managed_context


    session_id, upstream_access_token = get_client_session_info()

    # Per-session lock prevents duplicate context creation when
    # concurrent requests arrive for the same new session.
    lock = session_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        context = delegated_contexts.get(session_id)
        if context is None:
            context = DelegatedAuthContext(client_session_id=session_id)
        await context.initialize(upstream_access_token)
        # Re-insert resets TTL timer
        delegated_contexts[session_id] = context
        return context

