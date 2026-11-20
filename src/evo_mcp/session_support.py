# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit, authenticated conversation sessions for sessionless MCP clients."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from contextvars import ContextVar
from typing import Any

from fastmcp.server.dependencies import get_session
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.sessions import SessionId, SessionProvider
from fastmcp.server.transforms import GetToolNext, Transform
from fastmcp.tools.base import Tool
from fastmcp.utilities.versions import VersionSpec
from mcp_types import CallToolRequestParams

from evo_mcp.contexts.helpers import get_client_session_upstream_access_token, get_user_id_from_token

_modern_session_id: ContextVar[str | None] = ContextVar("evo_modern_session_id", default=None)
_LIFECYCLE_TOOLS = frozenset({"create_session", "end_session", "search_tools", "call_tool"})
_SESSION_DESCRIPTION = (
    "For a sessionless connection, first call create_session and pass its ID here on "
    "every call in this conversation. Legacy MCP sessions do not need this argument."
)


def _user_id() -> str:
    return get_user_id_from_token(get_client_session_upstream_access_token())


def _context_key(user_id: str, session_id: str) -> str:
    return hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()[:32]


async def validated_session_key(session_id: str) -> str:
    session = await get_session(session_id)
    user_id = _user_id()
    if await session.get("evo_owner") != user_id:
        raise ValueError("Invalid or unknown session.")
    # SessionProvider's store is TTL-bounded; refresh it on every stateful call.
    await session.set("evo_owner", user_id)
    return _context_key(user_id, session_id)


async def create_conversation_session() -> str:
    """Create an isolated conversation for a sessionless MCP client."""
    from fastmcp.server.sessions import create_session

    session_id = await create_session()
    session = await get_session(session_id)
    await session.set("evo_owner", _user_id())
    return session_id


async def end_conversation_session(session_id: SessionId) -> str:
    """End a conversation and discard its server-side context."""
    key = await validated_session_key(session_id)
    from evo_mcp.context import delegated_contexts

    delegated_contexts.pop(key, None)
    session = await get_session(session_id)
    await session.end()
    return "session ended"


class ConversationSessionProvider(SessionProvider):
    async def _list_tools(self) -> Sequence[Tool]:
        if self._tools is None:
            self._tools = [
                Tool.from_function(create_conversation_session, name="create_session"),
                Tool.from_function(end_conversation_session, name="end_session"),
            ]
        return self._tools


class ConversationSessionArguments(Transform):
    """Advertise a session ID without changing existing tool signatures."""

    @staticmethod
    def _with_session_id(tool: Tool) -> Tool:
        if tool.name in _LIFECYCLE_TOOLS:
            return tool
        schema: dict[str, Any] = tool.parameters
        return tool.model_copy(
            update={
                "parameters": {
                    **schema,
                    "properties": {
                        **schema.get("properties", {}),
                        "session_id": {"type": "string", "description": _SESSION_DESCRIPTION},
                    },
                }
            }
        )

    async def list_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        return [self._with_session_id(tool) for tool in tools]

    async def get_tool(self, name: str, call_next: GetToolNext, *, version: VersionSpec | None = None) -> Tool | None:
        tool = await call_next(name, version=version)
        return self._with_session_id(tool) if tool else None


class ConversationSessionMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext[CallToolRequestParams], call_next):
        request = context.fastmcp_context.request_context if context.fastmcp_context else None
        if request is None or request.protocol_version < "2026-07-28":
            return await call_next(context)

        name = context.message.name
        if name in _LIFECYCLE_TOOLS:
            return await call_next(context)

        arguments = dict(context.message.arguments or {})
        session_id = arguments.pop("session_id", None)
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("A sessionless tool call requires a session_id from create_session.")
        await validated_session_key(session_id)
        token = _modern_session_id.set(session_id)
        try:
            return await call_next(context.copy(message=context.message.model_copy(update={"arguments": arguments})))
        finally:
            _modern_session_id.reset(token)


def modern_session_id() -> str | None:
    return _modern_session_id.get()
