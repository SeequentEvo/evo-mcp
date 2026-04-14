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
from pathlib import Path

from cachetools import TTLCache
from dotenv import load_dotenv

from evo_mcp.contexts import DelegatedAuthContext, EvoContextBase, ManagedAuthContext
from evo_mcp.contexts.helpers import get_client_session_id

# Load environment variables from .env file
env_path = Path(__file__).parent.parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG if os.environ.get("DEBUG") == "1" else logging.INFO)


class _CleanupTTLCache(TTLCache):
    """TTLCache that calls ``cleanup()`` on evicted values.

    When a ``DelegatedAuthContext`` is evicted (TTL expiry or maxsize), its
    temporary directory is cleaned up promptly instead of waiting for GC.
    The matching ``session_locks`` entry is also removed.
    """

    def __init__(self, *args, locks: dict, **kwargs):
        super().__init__(*args, **kwargs)
        self._locks = locks

    def _cleanup_value(self, key: str, value: object) -> None:
        cleanup = getattr(value, "cleanup", None)
        if callable(cleanup):
            try:
                cleanup()
            except Exception:
                logger.exception("Failed to clean up context for session %s", key)
        self._locks.pop(key, None)

    def __delitem__(self, key):
        value = self[key]
        super().__delitem__(key)
        self._cleanup_value(key, value)

    def pop(self, key, *args):
        if key in self:
            value = self[key]
            result = super().pop(key)
            self._cleanup_value(key, value)
            return result
        return super().pop(key, *args)

    def popitem(self):
        key, value = super().popitem()
        self._cleanup_value(key, value)
        return key, value

    def clear(self):
        items = list(self.items())
        super().clear()
        for key, value in items:
            self._cleanup_value(key, value)


delegated_mode: bool = False
managed_context: ManagedAuthContext | None = None

SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "3600"))
MAX_SESSIONS = int(os.getenv("MAX_SESSIONS", "1000"))
session_locks: dict[str, asyncio.Lock] = {}
delegated_contexts: TTLCache[str, DelegatedAuthContext] = _CleanupTTLCache(
    maxsize=MAX_SESSIONS,
    ttl=SESSION_TTL_SECONDS,
    locks=session_locks,
)

# TODO: Move this to an environment manager module
MCP_TRANSPORT = os.getenv("MCP_TRANSPORT", "stdio").lower()
CLIENT_DELEGATED_AUTH_ENV = os.getenv("CLIENT_DELEGATED_AUTH", "false").lower() in ("true", "1")
AUTH_METHOD = os.getenv("AUTH_METHOD", "native_app").lower()

if CLIENT_DELEGATED_AUTH_ENV and MCP_TRANSPORT == "http":
    if AUTH_METHOD == "client_credentials":
        raise ValueError(
            "CLIENT_DELEGATED_AUTH=true is not supported with AUTH_METHOD=client_credentials. "
            "Delegated auth requires AUTH_METHOD=native_app (interactive browser login)."
        )
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
        global managed_context
        if managed_context is None:
            managed_context = ManagedAuthContext()
        await managed_context.initialize()
        return managed_context

    session_id = get_client_session_id()

    # Per-session lock prevents duplicate context creation when
    # concurrent requests arrive for the same new session.
    lock = session_locks.setdefault(session_id, asyncio.Lock())
    async with lock:
        context = delegated_contexts.get(session_id)
        if context is None:
            context = DelegatedAuthContext(client_session_id=session_id)
        await context.initialize()
        # Re-insert resets TTL timer
        delegated_contexts[session_id] = context
        return context
