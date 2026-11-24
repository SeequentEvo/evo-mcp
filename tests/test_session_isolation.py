# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for session isolation: context, object_staging, and object_registry.

Verifies that in delegated auth mode, each conversation gets its own
DelegatedAuthContext with independent StagingService and ObjectRegistry.
"""

import asyncio
import base64
import hashlib
import json
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from cachetools import TTLCache
from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier
from fastmcp.server.transforms.search import BM25SearchTransform

import evo_mcp.context as ctx_module
from evo_mcp.context import _CleanupTTLCache
from evo_mcp.contexts.delegated import DelegatedAuthContext
from evo_mcp.contexts.helpers import get_client_session_upstream_access_token, get_user_id_from_token
from evo_mcp.contexts.managed import ManagedAuthContext
from evo_mcp.session.resolver import ResolutionError
from evo_mcp.session_support import (
    ConversationSessionArguments,
    ConversationSessionMiddleware,
    ConversationSessionProvider,
    StatelessProtocolMiddleware,
    end_conversation_session,
)
from evo_mcp.staging.errors import StageNotFoundError
from evo_mcp.staging.models import StagedEnvelope

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_token(sub: str = "user-1", iat: int | None = None) -> str:
    """Return a minimal unsigned JWT with the given sub claim.

    ``iat`` defaults to the current POSIX time so successive calls with the
    same ``sub`` produce distinct token strings (simulating token refresh).
    Pass an explicit ``iat`` when you need a deterministic value.
    """
    if iat is None:
        iat = int(time.time())
    header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).rstrip(b"=")
    payload = base64.urlsafe_b64encode(json.dumps({"sub": sub, "iat": iat}).encode()).rstrip(b"=")
    return f"{header.decode()}.{payload.decode()}."


def _mock_access_token_obj(token: str):
    """Create a mock object mimicking FastMCP's AccessToken."""
    obj = MagicMock()
    obj.token = token
    return obj


async def _invoke_tool(client, bearer, name, arguments):
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Accept": "application/json, text/event-stream",
        "MCP-Protocol-Version": "2026-07-28",
        "mcp-method": "tools/call",
        "mcp-name": name,
    }
    params = {
        "name": name,
        "arguments": arguments,
        "_meta": {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        },
    }
    response = await client.post(
        "/mcp",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params},
    )
    response.raise_for_status()
    payload = (
        json.loads(response.text.split("data: ", 1)[1].splitlines()[0])
        if response.headers.get("content-type", "").startswith("text/event-stream")
        else response.json()
    )
    return payload["result"] if "result" in payload else {"isError": True, "error": payload["error"]}


async def _validated_key(session_id: str, *, refresh: bool = True) -> str:
    user_id = get_user_id_from_token(get_client_session_upstream_access_token())
    return hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Test: Different sessions get different contexts
# ---------------------------------------------------------------------------


class TestContextPerSession(unittest.IsolatedAsyncioTestCase):
    """get_evo_context() returns distinct contexts for distinct sessions."""

    async def test_different_sessions_get_different_contexts(self):
        token_a = _make_mock_token("user-A")
        token_b = _make_mock_token("user-B")

        # Save original state and set delegated mode
        orig_delegated_mode = ctx_module.delegated_mode
        orig_managed_context = ctx_module.managed_context
        ctx_module.delegated_mode = True
        ctx_module.managed_context = None

        # Clear caches
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()

        try:
            with (
                patch("evo_mcp.contexts.helpers.get_access_token") as mock_at,
                patch("evo_mcp.context.modern_session_id") as mock_session,
                patch("evo_mcp.context.validated_session_key", side_effect=_validated_key),
                patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock),
            ):
                # Session A
                mock_at.return_value = _mock_access_token_obj(token_a)
                mock_session.return_value = "session-AAA"

                context_a = await ctx_module.get_evo_context()

                # Session B
                mock_at.return_value = _mock_access_token_obj(token_b)
                mock_session.return_value = "session-BBB"

                context_b = await ctx_module.get_evo_context()

            self.assertIsNot(context_a, context_b)
            self.assertIsInstance(context_a, DelegatedAuthContext)
            self.assertIsInstance(context_b, DelegatedAuthContext)
            # Each has its own staging and registry
            self.assertIsNot(context_a.object_staging, context_b.object_staging)
            self.assertIsNot(context_a.object_registry, context_b.object_registry)
        finally:
            ctx_module.delegated_mode = orig_delegated_mode
            ctx_module.managed_context = orig_managed_context
            ctx_module.delegated_contexts.clear()
            ctx_module.session_locks.clear()


# ---------------------------------------------------------------------------
# Test: Staged objects are session-private
# ---------------------------------------------------------------------------


class TestStagingIsolation(unittest.IsolatedAsyncioTestCase):
    """Objects staged in session A are invisible to session B."""

    async def test_staging_isolation_between_sessions(self):
        token_a = _make_mock_token("user-A")
        token_b = _make_mock_token("user-B")

        ctx_module.delegated_mode = True
        ctx_module.managed_context = None
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()

        try:
            with (
                patch("evo_mcp.contexts.helpers.get_access_token") as mock_at,
                patch("evo_mcp.context.modern_session_id") as mock_session,
                patch("evo_mcp.context.validated_session_key", side_effect=_validated_key),
                patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock),
            ):
                # Create session A context
                mock_at.return_value = _mock_access_token_obj(token_a)
                mock_session.return_value = "session-AAA"
                context_a = await ctx_module.get_evo_context()

                # Create session B context
                mock_at.return_value = _mock_access_token_obj(token_b)
                mock_session.return_value = "session-BBB"
                context_b = await ctx_module.get_evo_context()

            # Use _put directly to bypass type/domain validation — the test only
            # cares that two sessions have separate stores, not about payload type.
            staging_a = context_a.object_staging
            staging_a._put(
                StagedEnvelope(
                    stage_id="stage-001",
                    object_type="variogram",
                    workspace_id=None,
                    source_ref={},
                    status="active",
                    updated_at="2026-01-01T00:00:00+00:00",
                    expires_at="2099-01-01T00:00:00+00:00",
                ),
                {"test": "payload"},
            )

            # Session A can retrieve it
            envelope, payload = staging_a.get_stage_payload("stage-001")
            self.assertEqual(envelope.stage_id, "stage-001")
            self.assertEqual(payload, {"test": "payload"})

            # Session B cannot see it
            staging_b = context_b.object_staging
            with self.assertRaises(StageNotFoundError):
                staging_b.get_stage_payload("stage-001")
        finally:
            ctx_module.delegated_mode = False
            ctx_module.delegated_contexts.clear()
            ctx_module.session_locks.clear()


# ---------------------------------------------------------------------------
# Test: Registered names are session-private
# ---------------------------------------------------------------------------


class TestRegistryIsolation(unittest.IsolatedAsyncioTestCase):
    """Names registered in session A are unresolvable in session B."""

    async def test_registry_isolation_between_sessions(self):
        token_a = _make_mock_token("user-A")
        token_b = _make_mock_token("user-B")

        ctx_module.delegated_mode = True
        ctx_module.managed_context = None
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()

        try:
            with (
                patch("evo_mcp.contexts.helpers.get_access_token") as mock_at,
                patch("evo_mcp.context.modern_session_id") as mock_session,
                patch("evo_mcp.context.validated_session_key", side_effect=_validated_key),
                patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock),
            ):
                mock_at.return_value = _mock_access_token_obj(token_a)
                mock_session.return_value = "session-AAA"
                context_a = await ctx_module.get_evo_context()

                mock_at.return_value = _mock_access_token_obj(token_b)
                mock_session.return_value = "session-BBB"
                context_b = await ctx_module.get_evo_context()

            # Stage and register in session A
            context_a.object_staging._put(
                StagedEnvelope(
                    stage_id="stage-reg-001",
                    object_type="variogram",
                    workspace_id=None,
                    source_ref={},
                    status="active",
                    updated_at="2026-01-01T00:00:00+00:00",
                    expires_at="2099-01-01T00:00:00+00:00",
                ),
                {"variogram": "data"},
            )
            context_a.object_registry.register(
                name="CU variogram",
                object_type="variogram",
                stage_id="stage-reg-001",
            )

            # Session A resolves successfully
            entry = context_a.object_registry.resolve("CU variogram")
            self.assertEqual(entry.name, "CU variogram")
            self.assertEqual(entry.stage_id, "stage-reg-001")

            # Session B cannot resolve the same name
            with self.assertRaises(ResolutionError):
                context_b.object_registry.resolve("CU variogram")
        finally:
            ctx_module.delegated_mode = False
            ctx_module.delegated_contexts.clear()
            ctx_module.session_locks.clear()


# ---------------------------------------------------------------------------
# Test: Same session ID reuses context
# ---------------------------------------------------------------------------


class TestSameSessionReusesContext(unittest.IsolatedAsyncioTestCase):
    """Repeated requests with same session ID return the same context."""

    async def test_same_session_returns_same_context(self):
        token = _make_mock_token("user-X")

        ctx_module.delegated_mode = True
        ctx_module.managed_context = None
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()

        try:
            with (
                patch("evo_mcp.contexts.helpers.get_access_token") as mock_at,
                patch("evo_mcp.context.modern_session_id", return_value="session-XYZ"),
                patch("evo_mcp.context.validated_session_key", side_effect=_validated_key),
                patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock),
            ):
                mock_at.return_value = _mock_access_token_obj(token)
                context_1 = await ctx_module.get_evo_context()

                # Register something to verify state persistence
                context_1.object_staging._put(
                    StagedEnvelope(
                        stage_id="stage-persist",
                        object_type="point_set",
                        workspace_id=None,
                        source_ref={},
                        status="active",
                        updated_at="2026-01-01T00:00:00+00:00",
                        expires_at="2099-01-01T00:00:00+00:00",
                    ),
                    {"points": []},
                )
                context_1.object_registry.register(
                    name="my points",
                    object_type="point_set",
                    stage_id="stage-persist",
                )

                # Second request with same session
                context_2 = await ctx_module.get_evo_context()

            self.assertIs(context_1, context_2)
            # Registry state persisted
            entry = context_2.object_registry.resolve("my points")
            self.assertEqual(entry.stage_id, "stage-persist")
        finally:
            ctx_module.delegated_mode = False
            ctx_module.delegated_contexts.clear()
            ctx_module.session_locks.clear()


# ---------------------------------------------------------------------------
# Test: TTL eviction calls cleanup
# ---------------------------------------------------------------------------


class TestTTLEvictionCleanup(unittest.TestCase):
    """Expired sessions are cleaned up and locks removed."""

    def test_ttl_eviction_calls_cleanup(self):
        locks: dict[str, asyncio.Lock] = {"session-1": asyncio.Lock()}
        cache: TTLCache = _CleanupTTLCache(maxsize=10, ttl=0.1, locks=locks)

        mock_context = MagicMock()
        mock_context.cleanup = MagicMock()

        cache["session-1"] = mock_context

        # Wait for TTL to expire
        time.sleep(0.2)

        # Trigger eviction by accessing/inserting (cachetools lazy eviction)
        cache["session-2"] = MagicMock()

        # session-1 should have been evicted
        self.assertNotIn("session-1", cache)
        # cleanup should have been called exactly once
        mock_context.cleanup.assert_called_once()
        # lock should be removed
        self.assertNotIn("session-1", locks)

    def test_explicit_delete_calls_cleanup_once(self):
        locks: dict[str, asyncio.Lock] = {"s": asyncio.Lock()}
        cache: TTLCache = _CleanupTTLCache(maxsize=10, ttl=60, locks=locks)
        mock_context = MagicMock()
        cache["s"] = mock_context

        del cache["s"]

        mock_context.cleanup.assert_called_once()
        self.assertNotIn("s", locks)

    def test_pop_calls_cleanup_once(self):
        locks: dict[str, asyncio.Lock] = {"s": asyncio.Lock()}
        cache: TTLCache = _CleanupTTLCache(maxsize=10, ttl=60, locks=locks)
        mock_context = MagicMock()
        cache["s"] = mock_context

        cache.pop("s")

        mock_context.cleanup.assert_called_once()
        self.assertNotIn("s", locks)

    def test_maxsize_eviction_calls_cleanup_once(self):
        locks: dict[str, asyncio.Lock] = {"s": asyncio.Lock()}
        cache: TTLCache = _CleanupTTLCache(maxsize=1, ttl=60, locks=locks)
        mock_context = MagicMock()
        cache["s"] = mock_context

        # Inserting a second item forces LRU eviction of "s"
        cache["s2"] = MagicMock()

        mock_context.cleanup.assert_called_once()
        self.assertNotIn("s", locks)

    def test_clear_calls_cleanup_once_per_item(self):
        locks: dict[str, asyncio.Lock] = {"a": asyncio.Lock(), "b": asyncio.Lock()}
        cache: TTLCache = _CleanupTTLCache(maxsize=10, ttl=60, locks=locks)
        ctx_a, ctx_b = MagicMock(), MagicMock()
        cache["a"] = ctx_a
        cache["b"] = ctx_b

        cache.clear()

        ctx_a.cleanup.assert_called_once()
        ctx_b.cleanup.assert_called_once()
        self.assertEqual(locks, {})


# ---------------------------------------------------------------------------
# Test: Lock prevents duplicate context creation
# ---------------------------------------------------------------------------


class TestConcurrentSessionCreation(unittest.IsolatedAsyncioTestCase):
    """Multiple concurrent get_evo_context() for same session create only one context."""

    async def test_concurrent_creation_single_context(self):
        token = _make_mock_token("user-concurrent")
        creation_count = 0

        original_init = DelegatedAuthContext.__init__

        def counting_init(self, *args, **kwargs):
            nonlocal creation_count
            creation_count += 1
            original_init(self, *args, **kwargs)

        ctx_module.delegated_mode = True
        ctx_module.managed_context = None
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()

        try:
            with (
                patch("evo_mcp.contexts.helpers.get_access_token") as mock_at,
                patch("evo_mcp.context.modern_session_id", return_value="session-concurrent"),
                patch("evo_mcp.context.validated_session_key", side_effect=_validated_key),
                patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock),
                patch.object(DelegatedAuthContext, "__init__", counting_init),
            ):
                mock_at.return_value = _mock_access_token_obj(token)
                # Launch 5 concurrent requests
                results = await asyncio.gather(*[ctx_module.get_evo_context() for _ in range(5)])

            # All should return the same instance
            for ctx in results[1:]:
                self.assertIs(results[0], ctx)

            # Only one context was created
            self.assertEqual(creation_count, 1)
        finally:
            ctx_module.delegated_mode = False
            ctx_module.delegated_contexts.clear()
            ctx_module.session_locks.clear()


# ---------------------------------------------------------------------------
# Test: Token refresh rebuilds clients but preserves staging/registry
# ---------------------------------------------------------------------------


class TestTokenRefreshPreservesState(unittest.IsolatedAsyncioTestCase):
    """Token change triggers client rebuild but staging/registry are preserved."""

    async def test_token_refresh_rebuilds_clients_preserves_state(self):
        # Two different tokens for the same user (iat differs → distinct strings)
        token_v1 = _make_mock_token("user-refresh", iat=1000)
        token_v2 = _make_mock_token("user-refresh", iat=2000)

        ctx_module.delegated_mode = True
        ctx_module.managed_context = None
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()

        try:
            with (
                patch("evo_mcp.contexts.helpers.get_access_token") as mock_at,
                patch("evo_mcp.context.modern_session_id", return_value="session-refresh"),
                patch("evo_mcp.context.validated_session_key", side_effect=_validated_key),
                patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock) as mock_build,
            ):
                # First request with token_v1
                mock_at.return_value = _mock_access_token_obj(token_v1)
                context = await ctx_module.get_evo_context()

                # Stage an object
                context.object_staging._put(
                    StagedEnvelope(
                        stage_id="stage-refresh",
                        object_type="variogram",
                        workspace_id=None,
                        source_ref={},
                        status="active",
                        updated_at="2026-01-01T00:00:00+00:00",
                        expires_at="2099-01-01T00:00:00+00:00",
                    ),
                    {"refreshed": True},
                )
                context.object_registry.register(
                    name="test vario",
                    object_type="variogram",
                    stage_id="stage-refresh",
                )

                build_count_before = mock_build.call_count

                # Second request with token_v2 (token refreshed)
                mock_at.return_value = _mock_access_token_obj(token_v2)
                context_after = await ctx_module.get_evo_context()

            # Same context instance (same session)
            self.assertIs(context, context_after)

            # discover_and_build was called again (clients rebuilt)
            self.assertGreater(mock_build.call_count, build_count_before)

            # Staging and registry state preserved
            entry = context_after.object_registry.resolve("test vario")
            self.assertEqual(entry.stage_id, "stage-refresh")
            _, payload = context_after.object_staging.get_stage_payload("stage-refresh")
            self.assertEqual(payload, {"refreshed": True})
        finally:
            ctx_module.delegated_mode = False
            ctx_module.delegated_contexts.clear()
            ctx_module.session_locks.clear()


# ---------------------------------------------------------------------------
# Test: Managed mode returns singleton
# ---------------------------------------------------------------------------


class TestManagedModeSharedContext(unittest.IsolatedAsyncioTestCase):
    """Managed mode returns the same context every time."""

    async def test_managed_mode_returns_singleton(self):
        ctx_module.delegated_mode = False
        ctx_module.managed_context = None

        try:
            with patch.object(ManagedAuthContext, "initialize", new_callable=AsyncMock):
                context_1 = await ctx_module.get_evo_context()
                context_2 = await ctx_module.get_evo_context()

            self.assertIs(context_1, context_2)
            self.assertIsInstance(context_1, ManagedAuthContext)
            # Staging and registry are the same instances
            self.assertIs(context_1.object_staging, context_2.object_staging)
            self.assertIs(context_1.object_registry, context_2.object_registry)
        finally:
            ctx_module.managed_context = None


# ---------------------------------------------------------------------------
# Test: Different users with same conversation ID get different contexts
# ---------------------------------------------------------------------------


class TestUserIsolation(unittest.IsolatedAsyncioTestCase):
    """Different users cannot share contexts even with the same conversation ID."""

    async def test_different_users_same_conversation_id_isolated(self):
        token_user1 = _make_mock_token("user-alice")
        token_user2 = _make_mock_token("user-bob")

        ctx_module.delegated_mode = True
        ctx_module.managed_context = None
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()

        try:
            with (
                patch("evo_mcp.contexts.helpers.get_access_token") as mock_at,
                patch("evo_mcp.context.modern_session_id", return_value="session-SHARED"),
                patch("evo_mcp.context.validated_session_key", side_effect=_validated_key),
                patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock),
            ):
                # User Alice with session-SHARED
                mock_at.return_value = _mock_access_token_obj(token_user1)
                context_alice = await ctx_module.get_evo_context()

                # User Bob with the same conversation ID
                mock_at.return_value = _mock_access_token_obj(token_user2)
                context_bob = await ctx_module.get_evo_context()

            # Context keys remain distinct despite the same conversation ID.
            self.assertIsNot(context_alice, context_bob)
        finally:
            ctx_module.delegated_mode = False
            ctx_module.delegated_contexts.clear()
            ctx_module.session_locks.clear()


@pytest.mark.asyncio
async def test_end_session_waits_for_context_initialization_and_cleans_it_up():
    initialized = asyncio.Event()
    resume = asyncio.Event()
    session = MagicMock()
    session.get = AsyncMock(return_value="alice")
    session.set = AsyncMock()
    session.end = AsyncMock()
    key = hashlib.sha256(b"alice:conversation").hexdigest()[:32]

    async def blocked_initialize(_context):
        initialized.set()
        await resume.wait()

    original_mode = ctx_module.delegated_mode
    ctx_module.delegated_mode = True
    ctx_module.delegated_contexts.clear()
    ctx_module.session_locks.clear()
    try:
        with (
            patch("evo_mcp.session_support._user_id", return_value="alice"),
            patch("evo_mcp.session_support.get_session", new_callable=AsyncMock, return_value=session),
            patch("evo_mcp.context.modern_session_id", return_value="conversation"),
            patch.object(DelegatedAuthContext, "initialize", blocked_initialize),
        ):
            pending_get = asyncio.create_task(ctx_module.get_evo_context())
            pending_end = None
            try:
                await asyncio.wait_for(initialized.wait(), 2)
                pending_end = asyncio.create_task(end_conversation_session("conversation"))
                await asyncio.sleep(0)
                assert not pending_end.done()

                resume.set()
                context = await asyncio.wait_for(pending_get, 2)
                assert await asyncio.wait_for(pending_end, 2) == "session ended"
                assert key not in ctx_module.delegated_contexts
                assert key not in ctx_module.session_locks
                assert not context.cache_path.exists()
                session.end.assert_awaited_once()
            finally:
                resume.set()
                await asyncio.gather(*(task for task in (pending_get, pending_end) if task), return_exceptions=True)
    finally:
        ctx_module.delegated_mode = original_mode
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()


@pytest.mark.asyncio
async def test_context_waiting_for_end_revalidates_before_initialization():
    ending = asyncio.Event()
    resume = asyncio.Event()
    active = True
    session = MagicMock()
    session.get = AsyncMock(return_value="alice")
    session.set = AsyncMock()

    async def get_session(session_id):
        if not active:
            raise ValueError("Invalid or unknown session.")
        return session

    async def end():
        nonlocal active
        ending.set()
        await resume.wait()
        active = False

    session.end = AsyncMock(side_effect=end)
    original_mode = ctx_module.delegated_mode
    ctx_module.delegated_mode = True
    ctx_module.delegated_contexts.clear()
    ctx_module.session_locks.clear()
    try:
        with (
            patch("evo_mcp.session_support._user_id", return_value="alice"),
            patch("evo_mcp.session_support.get_session", side_effect=get_session),
            patch("evo_mcp.context.modern_session_id", return_value="conversation"),
            patch.object(DelegatedAuthContext, "initialize", new_callable=AsyncMock) as initialize,
        ):
            pending_end = asyncio.create_task(end_conversation_session("conversation"))
            pending_get = None
            try:
                await asyncio.wait_for(ending.wait(), 2)
                pending_get = asyncio.create_task(ctx_module.get_evo_context())
                await asyncio.sleep(0)
                assert not pending_get.done()

                resume.set()
                assert await asyncio.wait_for(pending_end, 2) == "session ended"
                with pytest.raises(ValueError, match="Invalid or unknown session"):
                    await asyncio.wait_for(pending_get, 2)
                initialize.assert_not_awaited()
                assert not ctx_module.delegated_contexts
                assert not ctx_module.session_locks
                with pytest.raises(ValueError, match="Invalid or unknown session"):
                    await ctx_module.get_evo_context()
                with pytest.raises(ValueError, match="Invalid or unknown session"):
                    await end_conversation_session("conversation")
                assert not ctx_module.session_locks
            finally:
                resume.set()
                await asyncio.gather(*(task for task in (pending_end, pending_get) if task), return_exceptions=True)
    finally:
        ctx_module.delegated_mode = original_mode
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()


@pytest.mark.asyncio
@pytest.mark.parametrize("delegated", [False, True])
async def test_http_rejects_legacy_protocol_in_both_auth_modes(delegated):
    token = _make_mock_token("wire-user")
    auth = DebugTokenVerifier(validate=lambda value: value == token) if delegated else None
    mcp = FastMCP("session-test", auth=auth)
    mcp.add_middleware(StatelessProtocolMiddleware())

    @mcp.tool
    async def ping() -> str:
        return "pong"

    app = mcp.http_app(stateless_http=True)
    async with app.lifespan(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
            headers = {"Accept": "application/json, text/event-stream"}
            if delegated:
                headers["Authorization"] = f"Bearer {token}"
            legacy = await client.post(
                "/mcp",
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "1"},
                    },
                },
            )
            assert "mcp-session-id" not in legacy.headers
            assert "2026-07-28" in legacy.text
            assert "protocolVersion" not in legacy.text

            legacy_call = await client.post(
                "/mcp",
                headers={**headers, "MCP-Protocol-Version": "2025-03-26"},
                json={
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "ping", "arguments": {}},
                },
            )
            assert "2026-07-28" in legacy_call.text
            assert "pong" not in legacy_call.text

            modern = await client.post(
                "/mcp",
                headers={
                    **headers,
                    "MCP-Protocol-Version": "2026-07-28",
                    "mcp-method": "tools/call",
                    "mcp-name": "ping",
                },
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "_meta": {
                            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                            "io.modelcontextprotocol/clientCapabilities": {},
                        },
                        "name": "ping",
                        "arguments": {},
                    },
                },
            )
            modern.raise_for_status()
            assert modern.json()["result"]["content"][0]["text"] == "pong"
            assert "mcp-session-id" not in modern.headers


@pytest.mark.asyncio
async def test_session_id_is_required_without_losing_existing_required_fields():
    mcp = FastMCP("session-test")
    mcp.add_transform(ConversationSessionArguments())

    @mcp.tool
    async def echo(value: str) -> str:
        return value

    listed = {tool.name: tool for tool in await mcp.list_tools()}
    assert set(listed["echo"].parameters["required"]) == {"value", "session_id"}
    assert set((await mcp.get_tool("echo")).parameters["required"]) == {"value", "session_id"}


@pytest.mark.asyncio
async def test_end_session_waits_for_active_tool_to_finish():
    token = _make_mock_token("alice")
    mcp = FastMCP("session-test", auth=DebugTokenVerifier(validate=lambda value: value == token))
    mcp.add_provider(ConversationSessionProvider())
    mcp.add_transform(ConversationSessionArguments())
    mcp.add_middleware(StatelessProtocolMiddleware())
    mcp.add_middleware(ConversationSessionMiddleware())
    entered = asyncio.Event()
    resume = asyncio.Event()
    context_path = None

    @mcp.tool
    async def build_object() -> str:
        nonlocal context_path
        context = await ctx_module.get_evo_context()
        context_path = context.cache_path
        entered.set()
        await resume.wait()
        assert context_path.exists()
        return "built"

    app = mcp.http_app(stateless_http=True)
    original_mode = ctx_module.delegated_mode
    ctx_module.delegated_mode = True
    ctx_module.delegated_contexts.clear()
    ctx_module.session_locks.clear()
    try:
        with patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock):
            async with app.lifespan(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
                    created = await _invoke_tool(client, token, "create_session", {})
                    assert not created["isError"]
                    session_id = created["content"][0]["text"]
                    active_call = asyncio.create_task(
                        _invoke_tool(client, token, "build_object", {"session_id": session_id})
                    )
                    ending = None
                    queued_call = None
                    try:
                        await asyncio.wait_for(entered.wait(), 2)
                        ending = asyncio.create_task(
                            _invoke_tool(client, token, "end_session", {"session_id": session_id})
                        )
                        await asyncio.sleep(0.05)
                        assert not ending.done()
                        assert context_path.exists()
                        queued_call = asyncio.create_task(
                            _invoke_tool(client, token, "build_object", {"session_id": session_id})
                        )

                        resume.set()
                        assert not (await asyncio.wait_for(active_call, 2))["isError"]
                        assert not (await asyncio.wait_for(ending, 2))["isError"]
                        assert (await asyncio.wait_for(queued_call, 2))["isError"]
                        assert not context_path.exists()
                        assert (await _invoke_tool(client, token, "build_object", {"session_id": session_id}))[
                            "isError"
                        ]
                    finally:
                        resume.set()
                        await asyncio.gather(
                            *(task for task in (active_call, ending, queued_call) if task), return_exceptions=True
                        )
    finally:
        ctx_module.delegated_mode = original_mode
        ctx_module.delegated_contexts.clear()
        ctx_module.session_locks.clear()


@pytest.mark.asyncio
async def test_sessionless_conversations_are_isolated():
    alice = _make_mock_token("alice", iat=100)
    alice_refreshed = _make_mock_token("alice", iat=200)
    bob = _make_mock_token("bob", iat=100)
    mcp = FastMCP(
        "session-test", auth=DebugTokenVerifier(validate=lambda value: value in {alice, alice_refreshed, bob})
    )
    mcp.add_provider(ConversationSessionProvider())
    mcp.add_transform(ConversationSessionArguments())
    mcp.add_middleware(StatelessProtocolMiddleware())
    mcp.add_middleware(ConversationSessionMiddleware())

    @mcp.tool
    async def session_identity() -> str:
        context = await ctx_module.get_evo_context()
        return context.client_session_id

    mcp.add_transform(BM25SearchTransform(always_visible=["create_session", "end_session", "session_identity"]))
    listed = {tool.name: tool for tool in await mcp.list_tools()}
    assert "session_id" in listed["session_identity"].parameters["properties"]
    assert "session_id" in listed["session_identity"].parameters["required"]
    assert "session_id" not in listed["create_session"].parameters["properties"]
    app = mcp.http_app(stateless_http=True)

    original_mode = ctx_module.delegated_mode
    ctx_module.delegated_mode = True
    ctx_module.delegated_contexts.clear()
    try:
        with patch.object(DelegatedAuthContext, "discover_and_build", new_callable=AsyncMock):
            async with app.lifespan(app):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="https://test") as client:
                    first = await _invoke_tool(client, alice, "create_session", {})
                    second = await _invoke_tool(client, alice, "create_session", {})
                    assert not first["isError"] and not second["isError"]
                    first_id = first["content"][0]["text"]
                    second_id = second["content"][0]["text"]
                    assert first_id != second_id

                    async def identity(token, session_id, via_proxy=False):
                        args = {"session_id": session_id}
                        if via_proxy:
                            return await _invoke_tool(
                                client,
                                token,
                                "call_tool",
                                {
                                    "name": "session_identity",
                                    "arguments": args,
                                },
                            )
                        return await _invoke_tool(client, token, "session_identity", args)

                    a = await identity(alice, first_id)
                    first_key = hashlib.sha256(f"alice:{first_id}".encode()).hexdigest()[:32]
                    first_context = ctx_module.delegated_contexts[first_key]
                    again = await identity(alice_refreshed, first_id, via_proxy=True)
                    b = await identity(alice, second_id)
                    assert not a["isError"] and not again["isError"] and not b["isError"]
                    assert a["content"] == again["content"]
                    assert ctx_module.delegated_contexts[first_key] is first_context
                    assert a["content"] != b["content"]
                    assert (await identity(bob, first_id))["isError"]
                    assert (await identity(alice, "not-created"))["isError"]
                    assert (await _invoke_tool(client, alice, "session_identity", {}))["isError"]
                    ended = await _invoke_tool(client, alice, "end_session", {"session_id": first_id})
                    assert not ended["isError"]
                    assert first_key not in ctx_module.delegated_contexts
                    assert (await identity(alice, first_id))["isError"]
    finally:
        ctx_module.delegated_mode = original_mode
        ctx_module.delegated_contexts.clear()


# ---------------------------------------------------------------------------
# Test: Cache evicts LRU when maxsize reached
# ---------------------------------------------------------------------------


class TestCacheMaxsizeEviction(unittest.TestCase):
    """_CleanupTTLCache evicts least-recently-used when full."""

    def test_maxsize_eviction_calls_cleanup(self):
        locks: dict[str, asyncio.Lock] = {
            "session-A": asyncio.Lock(),
            "session-B": asyncio.Lock(),
            "session-C": asyncio.Lock(),
        }
        cache: TTLCache = _CleanupTTLCache(maxsize=2, ttl=3600, locks=locks)

        ctx_a = MagicMock()
        ctx_a.cleanup = MagicMock()
        ctx_b = MagicMock()
        ctx_b.cleanup = MagicMock()
        ctx_c = MagicMock()
        ctx_c.cleanup = MagicMock()

        cache["session-A"] = ctx_a
        cache["session-B"] = ctx_b

        # Inserting C should evict A (LRU)
        cache["session-C"] = ctx_c

        self.assertNotIn("session-A", cache)
        self.assertIn("session-B", cache)
        self.assertIn("session-C", cache)

        # cleanup called at least once on evicted context (may be called
        # multiple times due to cachetools internals — that's fine, cleanup()
        # is idempotent)
        ctx_a.cleanup.assert_called()
        ctx_b.cleanup.assert_not_called()
        ctx_c.cleanup.assert_not_called()

        # Lock for A should be removed
        self.assertNotIn("session-A", locks)


if __name__ == "__main__":
    unittest.main()
