# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Binary input capabilities, session isolation, limits and lifecycle."""

import asyncio
import gc
import hashlib
import os
import subprocess
import sys
import threading
import weakref
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastmcp import FastMCP
from fastmcp.server.auth.providers.debug import DebugTokenVerifier

import evo_mcp.file_transfer as transfer
from evo_mcp.contexts.delegated import DelegatedAuthContext
from evo_mcp.file_transfer import FileTransferError, FileTransfers


@pytest.fixture
def store(tmp_path):
    instance = FileTransfers(tmp_path)
    yield instance
    instance.cleanup()


@pytest.fixture
def app():
    mcp = FastMCP("file-transfer-test")
    transfer.register_file_transfer_routes(mcp)
    return mcp.http_app()


def prepare(store, data=b"original", name="input.bin"):
    return store.prepare(name, len(data), hashlib.sha256(data).hexdigest())


async def put(app, prepared, content, **kwargs):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        return await client.put("/file-transfer", headers=prepared["headers"], content=content, **kwargs)


@pytest.mark.parametrize("limit", ["0", "-1"])
def test_standalone_rejects_nonpositive_size_limit(limit):
    result = subprocess.run(
        [sys.executable, "-c", "import evo_mcp.file_transfer"],
        env={**os.environ, "EVO_MCP_REMOTE_FILE_TRANSFER_MAX_SIZE_BYTES": limit},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode != 0
    assert "EVO_MCP_REMOTE_FILE_TRANSFER_MAX_SIZE_BYTES must be a positive integer." in result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "data,name",
    [
        (b"\xef\xbb\xbfx,y,z\r\n1,2,3\r\n", "original.csv"),
        (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\xff\x80\x00", "original.png"),
        (b"", "empty.bin"),
    ],
)
async def test_exact_binary_input_and_single_use(app, store, data, name):
    prepared = prepare(store, data, name)
    assert prepared["method"] == "PUT"
    assert prepared["expires_in_seconds"] == 900
    assert prepared["file_ref"].startswith("upload:")
    assert "url" not in prepared
    assert not store._root.exists()
    with pytest.raises(FileTransferError, match="not complete"):
        store.resolve(prepared["file_ref"])
    response = await put(app, prepared, data)
    assert response.status_code == 200
    assert response.json() == {
        "status": "received",
        "file_ref": prepared["file_ref"],
        "file_name": name,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    path = store.resolve(prepared["file_ref"])
    assert path.name == name
    assert path.read_bytes() == data
    assert path.stat().st_mode & 0o222 == 0
    assert not list(store._root.glob("*.part"))
    assert (await put(app, prepared, data)).status_code == 401
    assert path.read_bytes() == data


@pytest.mark.parametrize(
    "name",
    ["", ".", "..", "../x", "/x", "a/b", r"a\b", r"C:\x", "C:x", "x\x00", "x\n", "x\x7f", "x\u202e", "x\ud800"],
)
def test_invalid_names(store, name):
    with pytest.raises(FileTransferError, match="filename"):
        prepare(store, name=name)


@pytest.mark.parametrize("size", [-1, True, 1.0, "1", None])
def test_invalid_sizes(store, size):
    with pytest.raises(FileTransferError, match="nonnegative integer"):
        store.prepare("x", size, "0" * 64)


@pytest.mark.parametrize("sha", ["", "a" * 63, "g" * 64, " " + "a" * 64, None])
def test_invalid_checksums(store, sha):
    with pytest.raises(FileTransferError, match="hexadecimal"):
        store.prepare("x", 1, sha)


def test_checksum_is_canonicalized(store):
    assert store.prepare("x", 0, "A" * 64)["sha256"] == "a" * 64


@pytest.mark.asyncio
async def test_authentication_and_method_restriction(app, store):
    prepared = prepare(store)
    token = prepared["headers"]["Authorization"]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for header in ["", "Bearer bad", "Basic bad", "Bearer oauth-access-token"]:
            response = await client.put("/file-transfer", headers={"Authorization": header}, content=b"original")
            assert response.status_code == 401
            assert token not in response.text
            assert str(store._root) not in response.text
        assert (await client.get("/file-transfer", headers=prepared["headers"])).status_code == 405
        assert (await client.put("/file-transfer?token=" + token.split(" ")[1], content=b"original")).status_code == 401
    assert (await put(app, prepared, b"original")).status_code == 200


@pytest.mark.asyncio
async def test_authenticated_mcp_custom_route_requires_only_upload_capability(store):
    oauth_token = "test-oauth-token"
    verifier = DebugTokenVerifier(validate=lambda token: token == oauth_token)
    mcp = FastMCP("authenticated-file-transfer-test", auth=verifier)
    transfer.register_file_transfer_routes(mcp)
    app = mcp.http_app()
    prepared = prepare(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # MCP remains OAuth protected, while the custom route authenticates its
        # own capability rather than demanding a second Authorization header.
        assert (await client.post("/mcp", json={})).status_code == 401
        oauth_only = await client.put(
            "/file-transfer",
            headers={"Authorization": f"Bearer {oauth_token}"},
            content=b"original",
        )
        assert oauth_only.status_code == 401
        assert (await client.put("/file-transfer", content=b"original")).status_code == 401
        response = await client.put("/file-transfer", headers=prepared["headers"], content=b"original")
        assert response.status_code == 200
        assert response.json()["status"] == "received"
    assert store.resolve(prepared["file_ref"]).read_bytes() == b"original"


@pytest.mark.asyncio
async def test_session_isolation_and_expiry(app, store, tmp_path, monkeypatch):
    other = FileTransfers(tmp_path)
    prepared = prepare(store)
    entry = store._entries[prepared["file_ref"]]
    assert (await put(app, prepared, b"original")).status_code == 200
    with pytest.raises(FileTransferError, match="this session"):
        other.resolve(prepared["file_ref"])
    for invalid in [str(store.resolve(prepared["file_ref"])), "/etc/passwd", "../file", "upload:unknown", None]:
        with pytest.raises(FileTransferError, match="this session"):
            store.resolve(invalid)
    monkeypatch.setattr(transfer.time, "monotonic", lambda: entry.expires_at + 1)
    with pytest.raises(FileTransferError, match="expired"):
        store.resolve(prepared["file_ref"])
    assert not entry.path.exists()
    assert not store._entries
    other.cleanup()


@pytest.mark.asyncio
async def test_expired_capability_rejected(app, store, monkeypatch):
    prepared = prepare(store)
    entry = store._entries[prepared["file_ref"]]
    monkeypatch.setattr(transfer.time, "monotonic", lambda: entry.expires_at + 1)
    response = await put(app, prepared, b"original")
    assert response.status_code == 410
    assert "expired" in response.json()["error"]
    assert entry.token not in transfer._capabilities


@pytest.mark.asyncio
async def test_per_file_and_reserved_session_quota(app, store, monkeypatch):
    monkeypatch.setattr(transfer, "MAX_REMOTE_FILE_TRANSFER_SIZE_BYTES", 10)
    with pytest.raises(FileTransferError, match="size limit"):
        prepare(store, b"x" * 11)
    first = prepare(store, b"x" * 6)
    with pytest.raises(FileTransferError, match="quota"):
        prepare(store, b"x" * 5)
    assert (await put(app, first, b"x" * 6)).status_code == 200
    second = prepare(store, b"x" * 4)
    with pytest.raises(FileTransferError, match="quota"):
        prepare(store, b"x")
    assert len(store._entries) == 2
    assert store.resolve(first["file_ref"]).read_bytes() == b"x" * 6
    store._entries[second["file_ref"]].expires_at = 0
    prepare(store, b"x" * 4)
    assert len(store._entries) == 2


def test_upload_count_bound_includes_zero_byte_files(store, monkeypatch):
    monkeypatch.setattr(transfer, "MAX_SESSION_FILE_TRANSFERS", 2)
    prepare(store, b"")
    prepare(store, b"")
    with pytest.raises(FileTransferError, match="count limit"):
        prepare(store, b"")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "chunks,status,message",
    [
        ([b"badbytes"], 400, "SHA-256"),
        ([b"ori", b"gin"], 400, "declared size"),
        ([b"original", b"extra"], 413, "declared size"),
    ],
)
async def test_failed_stream_cleans_partial_and_allows_retry(app, store, chunks, status, message):
    prepared = prepare(store)

    async def body():
        for chunk in chunks:
            yield chunk

    response = await put(app, prepared, body())
    assert response.status_code == status
    assert message in response.json()["error"]
    assert not list(store._root.rglob("*.*"))
    with pytest.raises(FileTransferError, match="not complete"):
        store.resolve(prepared["file_ref"])
    assert (await put(app, prepared, b"original")).status_code == 200


@pytest.mark.asyncio
async def test_content_length_rejected_before_writes(app, store):
    prepared = prepare(store)
    assert (await put(app, prepared, b"short")).status_code == 400
    assert not store._root.exists()
    assert (await put(app, prepared, b"original")).status_code == 200


@pytest.mark.asyncio
async def test_concurrent_upload_rejected(app, store):
    prepared = prepare(store)
    started, release = asyncio.Event(), asyncio.Event()

    async def body():
        yield b"orig"
        started.set()
        await release.wait()
        yield b"inal"

    first = asyncio.create_task(put(app, prepared, body()))
    await started.wait()
    try:
        assert (await put(app, prepared, b"original")).status_code == 409
    finally:
        release.set()
    assert (await first).status_code == 200


@pytest.mark.asyncio
async def test_cancellation_cleans_partial_and_allows_retry(app, store):
    prepared = prepare(store)
    started = asyncio.Event()

    async def body():
        yield b"orig"
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(put(app, prepared, body()))
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not list(store._root.glob("*.part"))
    assert not store._entries[prepared["file_ref"]].uploading
    assert (await put(app, prepared, b"original")).status_code == 200


@pytest.mark.asyncio
async def test_file_open_uses_worker_and_publication_stays_on_event_loop(app, store, monkeypatch):
    prepared = prepare(store)
    event_loop_thread = threading.get_ident()
    original_open, original_replace = Path.open, Path.replace
    operations = []

    def open_partial(path, *args, **kwargs):
        if path.suffix == ".part":
            assert threading.get_ident() != event_loop_thread
            operations.append("open")
        return original_open(path, *args, **kwargs)

    def publish_partial(path, target):
        assert threading.get_ident() == event_loop_thread
        operations.append("replace")
        return original_replace(path, target)

    monkeypatch.setattr(Path, "open", open_partial)
    monkeypatch.setattr(Path, "replace", publish_partial)
    assert (await put(app, prepared, b"original")).status_code == 200
    assert operations == ["open", "replace"]


@pytest.mark.asyncio
async def test_cancellation_during_open_waits_and_closes_created_file(app, store, monkeypatch):
    prepared = prepare(store)
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    original_open = Path.open
    handles = []

    def gated_open(path, *args, **kwargs):
        if path.suffix != ".part":
            return original_open(path, *args, **kwargs)
        loop.call_soon_threadsafe(started.set)
        assert release.wait(5), "test did not release file open"
        output = original_open(path, *args, **kwargs)
        handles.append(output)
        return output

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", gated_open)
        task = asyncio.create_task(put(app, prepared, b"original"))
        try:
            await asyncio.wait_for(started.wait(), 2)
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
        finally:
            release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert len(handles) == 1
    assert handles[0].closed
    assert not list(store._root.glob("*.part"))
    assert (await put(app, prepared, b"original")).status_code == 200


@pytest.mark.asyncio
async def test_cleanup_during_upload_does_not_publish_or_recreate_cache(app, store):
    prepared = prepare(store)
    started, release = asyncio.Event(), asyncio.Event()

    async def body():
        yield b"orig"
        started.set()
        await release.wait()
        yield b"inal"

    task = asyncio.create_task(put(app, prepared, body()))
    await started.wait()
    store.cleanup()
    release.set()
    assert (await task).status_code == 410
    assert not store._root.exists()
    assert (await put(app, prepared, b"original")).status_code == 401


@pytest.mark.asyncio
async def test_real_io_failures_propagate_but_partial_is_cleaned(app, store, monkeypatch):
    prepared = prepare(store)
    entry = store._entries[prepared["file_ref"]]

    def fail_publish(source, target):
        raise OSError("disk failure")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_publish)
        with pytest.raises(OSError, match="disk failure"):
            await put(app, prepared, b"original")
    assert not list(store._root.glob("*.part"))
    assert not entry.uploading
    assert prepared["file_ref"] not in store._entries
    assert (await put(app, prepared, b"original")).status_code == 401


@pytest.mark.asyncio
async def test_http_io_failure_does_not_expose_paths_or_capability(app, store, monkeypatch):
    prepared = prepare(store)

    def fail_publish(source, target):
        raise OSError(f"Cannot publish {source} to {target}")

    monkeypatch.setattr(Path, "replace", fail_publish)
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.put("/file-transfer", headers=prepared["headers"], content=b"original")
    assert response.status_code == 500
    assert str(store._root) not in response.text
    assert prepared["headers"]["Authorization"].split(" ")[1] not in response.text
    assert not list(store._root.glob("*.part"))


@pytest.mark.asyncio
async def test_disconnect_cleans_partial(app, store):
    prepared = prepare(store)
    events = iter([{"type": "http.request", "body": b"orig", "more_body": True}, {"type": "http.disconnect"}])
    sent = []

    async def receive():
        return next(events)

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "PUT",
            "scheme": "http",
            "path": "/file-transfer",
            "raw_path": b"/file-transfer",
            "query_string": b"",
            "root_path": "",
            "headers": [(key.lower().encode(), value.encode()) for key, value in prepared["headers"].items()],
            "server": ("test", 80),
            "client": ("client", 1234),
        },
        receive,
        send,
    )
    assert sent[0]["status"] == 400
    assert not list(store._root.glob("*.part"))
    assert (await put(app, prepared, b"original")).status_code == 200


@pytest.mark.asyncio
async def test_upload_duration_bounded_by_expiry(app, store, monkeypatch):
    monkeypatch.setattr(transfer, "FILE_TRANSFER_EXPIRY_SECONDS", 0.1)
    prepared = prepare(store)

    async def body():
        yield b"orig"
        await asyncio.sleep(10)

    response = await asyncio.wait_for(put(app, prepared, body()), timeout=2)
    assert response.status_code == 408
    assert not list(store._root.glob("*.part"))
    with pytest.raises(FileTransferError, match="expired"):
        store.resolve(prepared["file_ref"])


@pytest.mark.asyncio
async def test_cleanup_removes_files_and_revokes_tokens(app, store):
    completed = prepare(store)
    pending = prepare(store)
    assert (await put(app, completed, b"original")).status_code == 200
    path = store.resolve(completed["file_ref"])
    store.cleanup()
    assert not path.exists()
    assert not store._root.exists()
    assert (await put(app, pending, b"original")).status_code == 401
    with pytest.raises(FileTransferError, match="closed"):
        prepare(store)
    with pytest.raises(FileTransferError, match="this session"):
        store.resolve(completed["file_ref"])
    store.cleanup()


def test_no_global_strong_reference_to_store(tmp_path):
    store = FileTransfers(tmp_path)
    prepared = prepare(store)
    reference = weakref.ref(store)
    del store
    gc.collect()
    assert reference() is None
    assert prepared["headers"]["Authorization"].split(" ")[1] not in transfer._capabilities


def test_context_storage_is_lazy_and_cleanup_order(tmp_path, monkeypatch):
    monkeypatch.setattr("evo_mcp.contexts.delegated.get_session_cache_dir", lambda session_id: tmp_path / session_id)
    context = DelegatedAuthContext("session")
    assert context._file_transfers is None
    store = context.file_transfers
    assert context.file_transfers is store
    prepared = prepare(store)
    token = prepared["headers"]["Authorization"].split(" ")[1]
    cache_cleanup = context._temp_dir.cleanup

    def check_cleanup():
        assert token not in transfer._capabilities
        assert store._closed
        cache_cleanup()

    monkeypatch.setattr(context._temp_dir, "cleanup", check_cleanup)
    context.cleanup()
    assert not context.cache_path.exists()


@pytest.mark.asyncio
async def test_resolve_input_path_local_never_initializes_context(monkeypatch):
    get_context = AsyncMock(side_effect=AssertionError("Local paths must not initialize a context"))
    monkeypatch.setattr("evo_mcp.context.get_evo_context", get_context)
    monkeypatch.setattr(transfer, "REMOTE_FILE_TRANSFER", False)
    assert await transfer.resolve_input_path("~/nonexistent/../input.csv") == Path("~/nonexistent/../input.csv")
    get_context.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_input_path_hosted_uses_current_session(app, store, monkeypatch):
    prepared = prepare(store)
    assert (await put(app, prepared, b"original")).status_code == 200
    get_context = AsyncMock(return_value=SimpleNamespace(file_transfers=store))
    monkeypatch.setattr("evo_mcp.context.get_evo_context", get_context)
    monkeypatch.setattr(transfer, "REMOTE_FILE_TRANSFER", True)
    assert await transfer.resolve_input_path(prepared["file_ref"]) == store.resolve(prepared["file_ref"])
    with pytest.raises(FileTransferError, match="this session"):
        await transfer.resolve_input_path("/server/local/path")
    assert get_context.await_count == 2


@pytest.mark.asyncio
async def test_completed_expiry_starts_at_completion_and_resolve_touches(app, store, monkeypatch):
    now = [transfer.time.monotonic()]
    monkeypatch.setattr(transfer.time, "monotonic", lambda: now[0])
    prepared = prepare(store)
    entry = store._entries[prepared["file_ref"]]
    capability_deadline = entry.expires_at
    now[0] += 100
    with pytest.raises(FileTransferError, match="not complete"):
        store.resolve(prepared["file_ref"])
    assert entry.expires_at == capability_deadline
    assert (await put(app, prepared, b"original")).status_code == 200
    assert entry.expires_at == capability_deadline + 100
    now[0] += 800
    path = store.resolve(prepared["file_ref"])
    assert entry.expires_at == now[0] + 900
    now[0] += 899
    store._prune_expired()
    assert path.exists()
    now[0] += 1
    store._prune_expired()
    assert not path.exists()


@pytest.mark.asyncio
async def test_active_readers_defer_expiry_until_last_release(app, store, monkeypatch):
    prepared = prepare(store)
    assert (await put(app, prepared, b"original")).status_code == 200
    entry = store._entries[prepared["file_ref"]]
    with store.use(prepared["file_ref"]) as path:
        with store.use(prepared["file_ref"]):
            entry.expires_at = 0
            store._prune_expired()
            assert path.read_bytes() == b"original"
        assert entry.readers == 1
        entry.expires_at = 0
        store._prune_expired()
        assert path.exists()
    assert entry.readers == 0
    assert entry.expires_at > transfer.time.monotonic()


@pytest.mark.asyncio
async def test_context_eviction_and_gc_preserve_lease(app, tmp_path, monkeypatch):
    monkeypatch.setattr("evo_mcp.contexts.delegated.get_session_cache_dir", lambda session_id: tmp_path / session_id)
    context = DelegatedAuthContext("leased")
    store = context.file_transfers
    prepared = prepare(store)
    assert (await put(app, prepared, b"original")).status_code == 200
    cache_path = context.cache_path
    with store.use(prepared["file_ref"]) as path:
        with store.use(prepared["file_ref"]):
            context.cleanup()
            del context
            gc.collect()
            with pytest.raises(FileTransferError, match="this session"):
                store.resolve(prepared["file_ref"])
            assert path.read_bytes() == b"original"
        assert path.exists()
    assert not path.exists()
    assert not cache_path.exists()


@pytest.mark.asyncio
async def test_lifespan_sweeps_without_requests_and_awaits_task_shutdown(app, tmp_path, monkeypatch):
    monkeypatch.setattr(transfer, "get_cache_dir", lambda: tmp_path)
    monkeypatch.setattr(transfer, "FILE_TRANSFER_CLEANUP_INTERVAL_SECONDS", 0.01)
    mcp = FastMCP("transfer-lifespan", lifespan=transfer.file_transfer_lifespan)
    transfer.register_file_transfer_routes(mcp)
    app = mcp.http_app()
    async with app.router.lifespan_context(app):
        store = FileTransfers(tmp_path / "unused-context-cache")
        prepared = prepare(store)
        assert (await put(app, prepared, b"original")).status_code == 200
        entry = store._entries[prepared["file_ref"]]
        entry.expires_at = 0
        for _ in range(100):
            if not entry.path.exists():
                break
            await asyncio.sleep(0.01)
        assert not entry.path.exists()
        assert not store._entries
        prepare(store)
    assert store._closed
    assert not store._root.exists()
    assert not any(task.get_name() == "file-transfer-cleanup" for task in asyncio.all_tasks())


@pytest.mark.asyncio
async def test_lifespan_propagates_caller_cancellation_during_shutdown(tmp_path, monkeypatch):
    monkeypatch.setattr(transfer, "get_cache_dir", lambda: tmp_path)
    started, stopping, release, finish = (asyncio.Event() for _ in range(4))
    stores = []

    async def gated_sweeper():
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopping.set()
            await release.wait()

    async def run_server():
        async with transfer.file_transfer_lifespan(None):
            stores.append(FileTransfers(tmp_path))
            await finish.wait()

    monkeypatch.setattr(transfer, "_cleanup_expired", gated_sweeper)
    server = asyncio.create_task(run_server())
    sweepers = []
    try:
        await asyncio.wait_for(started.wait(), 2)
        sweepers = [task for task in asyncio.all_tasks() if task.get_name() == "file-transfer-cleanup"]
        finish.set()
        await asyncio.wait_for(stopping.wait(), 2)
        server.cancel()
        with pytest.raises(asyncio.CancelledError):
            await server
        assert stores[0]._closed
        assert transfer._process_storage is None
    finally:
        release.set()
        await asyncio.gather(*sweepers, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["write", "flush", "close"])
async def test_stream_io_failures_revoke_reservation(app, store, monkeypatch, operation):
    prepared = prepare(store)
    entry = store._entries[prepared["file_ref"]]
    original_open = Path.open

    class BrokenOutput:
        def __init__(self, output):
            self.output = output

        def __getattr__(self, name):
            return getattr(self.output, name)

        def write(self, chunk):
            if operation == "write":
                raise OSError("write failed")
            return self.output.write(chunk)

        def flush(self):
            if operation == "flush":
                raise OSError("flush failed")
            self.output.flush()

        def close(self):
            self.output.close()
            if operation == "close":
                raise OSError("close failed")

    def open_partial(path, *args, **kwargs):
        output = original_open(path, *args, **kwargs)
        return BrokenOutput(output) if path.suffix == ".part" else output

    monkeypatch.setattr(Path, "open", open_partial)
    with pytest.raises(OSError, match=f"{operation} failed"):
        await put(app, prepared, b"original")
    assert not entry.uploading
    assert entry.token not in transfer._capabilities
    assert prepared["file_ref"] not in store._entries
    assert not entry.path.exists()
    assert not entry.partial_path.exists()
    assert (await put(app, prepared, b"original")).status_code == 401


@pytest.mark.asyncio
async def test_unlink_failure_revokes_and_sweeper_retries(app, store, monkeypatch):
    prepared = prepare(store)
    entry = store._entries[prepared["file_ref"]]
    original_unlink = Path.unlink

    def fail_unlink(path, *args, **kwargs):
        if path.suffix == ".part":
            raise OSError("unlink failed")
        return original_unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_unlink)
        with pytest.raises(OSError, match="unlink failed"):
            await put(app, prepared, b"original")
        assert not entry.uploading
        assert entry.token not in transfer._capabilities
        # Other calls may also surface the actual pending cleanup I/O error.
        with monkeypatch.context() as resolve_patch:
            resolve_patch.setattr(store, "_prune_expired", lambda: None)
            with pytest.raises(FileTransferError, match="this session"):
                store.resolve(prepared["file_ref"])
    store._prune_expired()
    assert prepared["file_ref"] not in store._entries
    assert not entry.path.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["write", "flush"])
@pytest.mark.parametrize("io_failure", [False, True])
async def test_repeated_cancellation_waits_for_active_worker(app, store, monkeypatch, operation, io_failure):
    prepared = prepare(store)
    entry = store._entries[prepared["file_ref"]]
    started, release = asyncio.Event(), threading.Event()
    loop = asyncio.get_running_loop()
    original_open = Path.open

    class GatedOutput:
        def __init__(self, output):
            self.output = output
            self.busy = False

        def __getattr__(self, name):
            return getattr(self.output, name)

        def gated(self, method, *args):
            self.busy = True
            loop.call_soon_threadsafe(started.set)
            try:
                assert release.wait(5), "test did not release worker"
                if io_failure:
                    raise OSError("worker failed")
                return method(*args)
            finally:
                self.busy = False

        def write(self, chunk):
            return self.gated(self.output.write, chunk) if operation == "write" else self.output.write(chunk)

        def flush(self):
            return self.gated(self.output.flush) if operation == "flush" else self.output.flush()

        def close(self):
            assert not self.busy, "cleanup raced an active worker"
            self.output.close()

    def open_partial(path, *args, **kwargs):
        output = original_open(path, *args, **kwargs)
        return GatedOutput(output) if path.suffix == ".part" else output

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", open_partial)
        task = asyncio.create_task(put(app, prepared, b"original"))
        await asyncio.wait_for(started.wait(), 2)
        try:
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            assert not task.done()
            assert entry.uploading
            assert entry.partial_path.exists()
        finally:
            release.set()
        with pytest.raises(OSError if io_failure else asyncio.CancelledError):
            await task
    assert not entry.uploading
    assert not entry.partial_path.exists()
    assert (await put(app, prepared, b"original")).status_code == (401 if io_failure else 200)


def test_startup_reclaims_only_abandoned_owned_roots(tmp_path):
    root = tmp_path / "file-transfers"
    root.mkdir()
    abandoned = root / ("process-" + "a" * 32)
    abandoned.mkdir()
    (abandoned / ".owner").touch()
    (abandoned / "private-input").write_bytes(b"old data")
    unrelated = root / "unrelated"
    unrelated.mkdir()
    (unrelated / "keep").write_bytes(b"unrelated data")
    active = transfer._ProcessStorage(root)
    (active.path / "live").write_bytes(b"live input")
    assert not abandoned.exists()
    second = transfer._ProcessStorage(root)
    assert (active.path / "live").read_bytes() == b"live input"
    assert (unrelated / "keep").read_bytes() == b"unrelated data"
    active._finalizer()
    second._finalizer()


@pytest.mark.parametrize("during_startup", [True, False])
def test_interrupted_process_cleanup_preserves_ownership_for_retry(tmp_path, monkeypatch, during_startup):
    root = tmp_path / "file-transfers"
    if during_startup:
        abandoned = root / ("process-" + "a" * 32)
        abandoned.mkdir(parents=True)
        (abandoned / ".owner").touch()
    else:
        storage = transfer._ProcessStorage(root)
        abandoned = storage.path
    payload = abandoned / "input"
    payload.mkdir()
    (payload / "bytes").write_bytes(b"original")
    original_remove = transfer.shutil.rmtree

    def interrupted(path, *args, **kwargs):
        if path == payload:
            raise OSError("interrupted deletion")
        return original_remove(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(transfer.shutil, "rmtree", interrupted)
        cleanup = (lambda: transfer._ProcessStorage(root)) if during_startup else storage._finalizer
        with pytest.raises(OSError, match="interrupted deletion"):
            cleanup()
    assert (abandoned / ".owner").is_file()
    replacement = transfer._ProcessStorage(root)
    assert not abandoned.exists()
    replacement._finalizer()


def test_process_removal_holds_registry_lock(tmp_path, monkeypatch):
    import fcntl

    root = tmp_path / "file-transfers"
    storage = transfer._ProcessStorage(root)
    original_remove = transfer._ProcessStorage._remove_directory
    checked = []

    def remove(path):
        with (root / ".registry.lock").open("a+b") as registry:
            with pytest.raises(BlockingIOError):
                fcntl.flock(registry, fcntl.LOCK_EX | fcntl.LOCK_NB)
        checked.append(path)
        original_remove(path)

    monkeypatch.setattr(transfer._ProcessStorage, "_remove_directory", staticmethod(remove))
    storage._finalizer()
    assert checked == [storage.path]


@pytest.mark.asyncio
async def test_shutdown_retains_process_ownership_until_reader_finishes(app, tmp_path, monkeypatch):
    monkeypatch.setattr(transfer, "get_cache_dir", lambda: tmp_path)
    lease = None
    try:
        async with transfer.file_transfer_lifespan(None):
            store = FileTransfers(tmp_path)
            prepared = prepare(store)
            assert (await put(app, prepared, b"original")).status_code == 200
            process_path = store._storage.path
            lease = store.use(prepared["file_ref"])
            path = lease.__enter__()
        assert path.read_bytes() == b"original"
        other = transfer._ProcessStorage(tmp_path / "file-transfers")
        assert path.exists()
        other._finalizer()
    finally:
        if lease is not None:
            lease.__exit__(None, None, None)
    assert not process_path.exists()
