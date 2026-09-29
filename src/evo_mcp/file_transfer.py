# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Session-private binary input, authenticated by single-use upload capabilities.

The configured size limit applies both per file and to the sum of all reserved
input bytes in a session, including completed files until they expire.
"""

import asyncio
import hashlib
import logging
import os
import re
import secrets
import shutil
import time
import unicodedata
import weakref
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from uuid import uuid4

import anyio
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse

from evo_mcp.runtime_paths import get_cache_dir

logger = logging.getLogger(__name__)

REMOTE_FILE_TRANSFER = os.getenv("EVO_MCP_REMOTE_FILE_TRANSFER", "").lower() in ("true", "1")
MAX_REMOTE_FILE_TRANSFER_SIZE_BYTES = int(os.getenv("EVO_MCP_REMOTE_FILE_TRANSFER_MAX_SIZE_BYTES", "52428800"))
if MAX_REMOTE_FILE_TRANSFER_SIZE_BYTES <= 0:
    raise ValueError("EVO_MCP_REMOTE_FILE_TRANSFER_MAX_SIZE_BYTES must be a positive integer.")
MAX_SESSION_FILE_TRANSFERS = 100
FILE_TRANSFER_EXPIRY_SECONDS = 15 * 60
FILE_TRANSFER_CLEANUP_INTERVAL_SECONDS = 60
_OWNER_FILE_NAME = ".owner"


class FileTransferError(ValueError):
    """An invalid transfer request, safe to expose without paths or credentials."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


@dataclass
class _Upload:
    store: weakref.ReferenceType
    file_ref: str
    token: str
    file_name: str
    size_bytes: int
    sha256: str
    expires_at: float
    directory: Path
    uploading: bool = False
    completed: bool = False
    readers: int = 0
    discarded: bool = False

    @property
    def path(self) -> Path:
        return self.directory / self.file_name

    @property
    def partial_path(self) -> Path:
        return self.directory.with_suffix(".part")


# Only the owning session keeps entries alive. Neither this index nor an entry
# keeps an evicted context/store alive.
_capabilities: weakref.WeakValueDictionary[str, _Upload] = weakref.WeakValueDictionary()
_stores: weakref.WeakSet = weakref.WeakSet()
_process_storage = None


class _ProcessStorage:
    """Own a narrowly scoped, locked directory; reclaim only abandoned owners."""

    def __init__(self, root: Path):
        # Hosted deployments use POSIX filesystem locks. Local Windows mode
        # never constructs this storage and can still import the module.
        import fcntl

        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Serialize discovery/creation so a new owner cannot be mistaken for
        # an abandoned one in the interval before it acquires its own lock.
        with (root / ".registry.lock").open("a+b") as registry:
            fcntl.flock(registry, fcntl.LOCK_EX)
            for candidate in root.iterdir():
                if (
                    re.fullmatch(r"process-[0-9a-f]{32}", candidate.name) is None
                    or candidate.is_symlink()
                    or not candidate.is_dir()
                ):
                    continue
                try:
                    descriptor = os.open(candidate / _OWNER_FILE_NAME, os.O_RDWR | os.O_NOFOLLOW)
                except FileNotFoundError:
                    # An interrupted mkdir before owner creation contains no data.
                    try:
                        if not any(candidate.iterdir()):
                            candidate.rmdir()
                    except FileNotFoundError:
                        pass
                    continue
                with os.fdopen(descriptor, "r+b") as owner:
                    try:
                        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        continue
                    self._remove_directory(candidate)
            self.path = root / f"process-{uuid4().hex}"
            self.path.mkdir(mode=0o700)
            owner = (self.path / _OWNER_FILE_NAME).open("x+b")
            fcntl.flock(owner, fcntl.LOCK_EX)
        self._finalizer = weakref.finalize(self, self._remove, self.path, owner)

    @staticmethod
    def _remove(path, owner):
        import fcntl

        try:
            with (path.parent / ".registry.lock").open("a+b") as registry:
                fcntl.flock(registry, fcntl.LOCK_EX)
                _ProcessStorage._remove_directory(path)
        finally:
            owner.close()

    @staticmethod
    def _remove_directory(path: Path) -> None:
        # Keep ownership evidence until deletion succeeds, so an interrupted
        # cleanup can be retried safely on the next startup.
        for child in path.iterdir():
            if child.name == _OWNER_FILE_NAME:
                continue
            if child.is_dir() and not child.is_symlink():
                shutil.rmtree(child)
            else:
                child.unlink()
        (path / _OWNER_FILE_NAME).unlink()
        path.rmdir()


async def _cleanup_expired() -> None:
    while True:
        await asyncio.sleep(FILE_TRANSFER_CLEANUP_INTERVAL_SECONDS)
        for store in _stores:
            try:
                store._prune_expired()
            except OSError:
                logger.exception("Could not remove expired temporary file input")


@asynccontextmanager
async def file_transfer_lifespan(mcp):
    """Sweep idle inputs and reclaim abandoned process storage at startup."""
    global _process_storage
    if _process_storage is not None:
        raise RuntimeError("File transfer lifespan is already running.")
    _process_storage = _ProcessStorage(get_cache_dir() / "file-transfers")
    task = asyncio.create_task(_cleanup_expired(), name="file-transfer-cleanup")
    try:
        yield {}
    finally:
        task.cancel()
        try:
            # Wait for the child without confusing its expected cancellation
            # with cancellation of the enclosing lifespan.
            await asyncio.wait({task})
            if not task.cancelled():
                task.result()
        finally:
            for store in _stores:
                try:
                    store.cleanup()
                except OSError:
                    logger.exception("Could not remove temporary file input at shutdown")
            # Stores with active leases retain the owner lock until their final use.
            _process_storage = None


async def _run_io(function, *args):
    """Do not let cancellation leave a file worker racing with cleanup."""
    worker = asyncio.create_task(anyio.to_thread.run_sync(function, *args))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        with anyio.CancelScope(shield=True):
            while not worker.done():
                try:
                    await asyncio.shield(worker)
                except asyncio.CancelledError:
                    continue
                except Exception:
                    break
            try:
                worker.result()
            except Exception:
                logger.exception("Temporary input I/O failed while cancelling upload")
                raise
        raise


class FileTransfers:
    """Bounded temporary input owned by one Evo context, never an Evo workspace."""

    def __init__(self, cache_path: Path):
        self._storage = _process_storage
        self._root = (self._storage.path if self._storage is not None else cache_path) / f"file-transfers-{uuid4()}"
        self._entries: dict[str, _Upload] = {}
        self._closed = False
        self._on_cleanup = None
        self._finalizer = weakref.finalize(self, shutil.rmtree, self._root, True)
        _stores.add(self)

    def _discard(self, entry: _Upload) -> None:
        entry.discarded = True
        _capabilities.pop(entry.token, None)
        if entry.readers or entry.uploading:
            return
        entry.partial_path.unlink(missing_ok=True)
        try:
            shutil.rmtree(entry.directory)
        except FileNotFoundError:
            pass
        self._entries.pop(entry.file_ref, None)
        self._finish_cleanup()

    def _finish_cleanup(self) -> None:
        if not self._closed or self._entries:
            return
        try:
            self._root.rmdir()
        except FileNotFoundError:
            pass
        self._finalizer.detach()
        self._storage = None
        if self._on_cleanup is not None:
            callback, self._on_cleanup = self._on_cleanup, None
            callback()

    def _prune_expired(self) -> None:
        now = time.monotonic()
        for entry in list(self._entries.values()):
            if entry.discarded or (not entry.readers and now >= entry.expires_at):
                self._discard(entry)

    def _ensure_active(self, entry: _Upload) -> None:
        if (
            self._closed
            or entry.discarded
            or self._entries.get(entry.file_ref) is not entry
            or time.monotonic() >= entry.expires_at
        ):
            raise FileTransferError("Upload has expired or its session was closed.", 410)

    def prepare(self, file_name: str, size_bytes: int, sha256: str) -> dict:
        """Reserve bytes and issue a capability; no workspace file is created."""
        self._prune_expired()
        if self._closed:
            raise FileTransferError("File transfer session is closed.", 410)
        if (
            not isinstance(file_name, str)
            or not file_name
            or file_name in (".", "..")
            or "/" in file_name
            or "\\" in file_name
            or ":" in file_name
            or PureWindowsPath(file_name).drive
            or any(unicodedata.category(char) in ("Cc", "Cf", "Cs") for char in file_name)
        ):
            raise FileTransferError("file_name must be a filename, not a path, without control characters.")
        if not isinstance(size_bytes, int) or isinstance(size_bytes, bool) or size_bytes < 0:
            raise FileTransferError("size_bytes must be a nonnegative integer.")
        if not isinstance(sha256, str) or re.fullmatch(r"[0-9a-fA-F]{64}", sha256) is None:
            raise FileTransferError("sha256 must contain 64 hexadecimal characters.")
        sha256 = sha256.lower()
        if size_bytes > MAX_REMOTE_FILE_TRANSFER_SIZE_BYTES:
            raise FileTransferError("File exceeds the temporary input size limit.", 413)
        if sum(entry.size_bytes for entry in self._entries.values()) + size_bytes > MAX_REMOTE_FILE_TRANSFER_SIZE_BYTES:
            raise FileTransferError(
                "Session temporary input quota exceeded. Wait for unused inputs to expire after 15 minutes.", 413
            )
        if len(self._entries) >= MAX_SESSION_FILE_TRANSFERS:
            raise FileTransferError(
                "Session temporary input count limit exceeded. Wait for unused inputs to expire after 15 minutes.", 429
            )

        identifier = str(uuid4())
        entry = _Upload(
            store=weakref.ref(self),
            file_ref=f"upload:{identifier}",
            token=secrets.token_urlsafe(32),
            file_name=file_name,
            size_bytes=size_bytes,
            sha256=sha256,
            expires_at=time.monotonic() + FILE_TRANSFER_EXPIRY_SECONDS,
            directory=self._root / identifier,
        )
        self._entries[entry.file_ref] = entry
        _capabilities[entry.token] = entry
        return {
            "file_ref": entry.file_ref,
            "method": "PUT",
            "headers": {
                "Authorization": f"Bearer {entry.token}",
                "Content-Type": "application/octet-stream",
            },
            "size_bytes": size_bytes,
            "sha256": sha256,
            "expires_in_seconds": FILE_TRANSFER_EXPIRY_SECONDS,
        }

    def resolve(self, file_ref: str) -> Path:
        """Resolve only this session's completed, unexpired opaque references."""
        self._prune_expired()
        entry = self._entries.get(file_ref) if isinstance(file_ref, str) else None
        if self._closed or entry is None or entry.discarded:
            raise FileTransferError("Unknown or expired file_ref for this session.")
        if not entry.completed:
            raise FileTransferError("File upload is not complete.", 409)
        entry.expires_at = time.monotonic() + FILE_TRANSFER_EXPIRY_SECONDS
        return entry.path

    @contextmanager
    def use(self, file_ref: str):
        """Lease an immutable completed input across awaits, including eviction."""
        path = self.resolve(file_ref)
        entry = self._entries[file_ref]
        entry.readers += 1
        try:
            yield path
        finally:
            entry.readers -= 1
            if entry.discarded or self._closed:
                self._discard(entry)
            else:
                entry.expires_at = time.monotonic() + FILE_TRANSFER_EXPIRY_SECONDS

    def cleanup(self, on_cleanup=None) -> None:
        """Invalidate capabilities before removing session-owned temporary data."""
        self._closed = True
        if on_cleanup is not None:
            self._on_cleanup = on_cleanup
        for entry in list(self._entries.values()):
            self._discard(entry)
        self._finish_cleanup()


def _authenticate(request: Request) -> tuple[FileTransfers, _Upload]:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    entry = _capabilities.get(token) if scheme.lower() == "bearer" else None
    store = entry.store() if entry is not None else None
    if store is None:
        raise FileTransferError("Unknown, expired, or already used upload capability.", 401)
    store._prune_expired()
    store._ensure_active(entry)
    if entry.uploading:
        raise FileTransferError("Upload is already in progress.", 409)
    return store, entry


async def _receive(request: Request, store: FileTransfers, entry: _Upload) -> dict:
    content_length = request.headers.get("content-length")
    if content_length is not None and content_length != str(entry.size_bytes):
        raise FileTransferError("Content-Length does not match the declared size.")

    entry.uploading = True
    # A separate directory ensures even a filename such as 'body.part' cannot
    # collide with the partial file. Completed input retains its original name.
    partial = entry.partial_path
    output = None
    digest = hashlib.sha256()
    received = 0

    def open_partial() -> None:
        nonlocal output
        # Retain the handle even if cancellation interrupts the awaiting task.
        output = partial.open("xb")

    def write_chunk(chunk: bytes) -> None:
        output.write(chunk)
        digest.update(chunk)

    try:
        with anyio.fail_after(max(0, entry.expires_at - time.monotonic())) as deadline:
            # Create directories before yielding so session cleanup cannot race
            # with a worker that recreates an already-removed session cache.
            store._root.mkdir(exist_ok=True, mode=0o700)
            entry.directory.mkdir(exist_ok=True, mode=0o700)
            await _run_io(open_partial)
            async for chunk in request.stream():
                store._ensure_active(entry)
                received += len(chunk)
                if received > entry.size_bytes:
                    raise FileTransferError("Upload exceeds the declared size.", 413)
                await _run_io(write_chunk, chunk)
            if received != entry.size_bytes:
                raise FileTransferError("Upload does not match the declared size.")
            if digest.hexdigest() != entry.sha256:
                raise FileTransferError("Upload SHA-256 does not match.")
            await _run_io(output.flush)
            os.fchmod(output.fileno(), 0o400)
            output.close()
            store._ensure_active(entry)
            partial.replace(entry.path)
            store._ensure_active(entry)
            entry.completed = True
            entry.expires_at = time.monotonic() + FILE_TRANSFER_EXPIRY_SECONDS
            _capabilities.pop(entry.token, None)
        return {
            "status": "received",
            "file_ref": entry.file_ref,
            "file_name": entry.file_name,
            "size_bytes": entry.size_bytes,
            "sha256": entry.sha256,
        }
    except TimeoutError:
        if deadline.cancel_called:
            raise FileTransferError("Upload expired before completion.", 408) from None
        raise
    except OSError:
        entry.discarded = True
        raise
    finally:
        # Workers have finished before this synchronous cleanup runs, including
        # after direct/repeated asyncio cancellation, not just AnyIO cancellation.
        try:
            if output is not None:
                try:
                    output.close()
                except OSError:
                    entry.discarded = True
                    raise
        finally:
            try:
                partial.unlink(missing_ok=True)
                if not entry.completed:
                    entry.path.unlink(missing_ok=True)
            except OSError:
                entry.discarded = True
                raise
            finally:
                entry.uploading = False
                if entry.discarded:
                    store._discard(entry)


def register_file_transfer_routes(mcp) -> None:
    """Add a fixed, independently capability-authenticated binary PUT route."""

    @mcp.custom_route("/file-transfer", methods=["PUT"])
    async def receive_file(request: Request) -> JSONResponse:
        try:
            store, entry = _authenticate(request)
            result = await _receive(request, store, entry)
        except FileTransferError as exc:
            return JSONResponse({"error": str(exc)}, status_code=exc.status_code)
        except ClientDisconnect:
            return JSONResponse({"error": "Upload disconnected before completion."}, status_code=400)
        return JSONResponse(result)


async def resolve_input_path(file_path: str) -> Path:
    """Keep local paths unchanged; hosted input must be a session-local file_ref."""
    if not REMOTE_FILE_TRANSFER:
        return Path(file_path)
    from evo_mcp.context import get_evo_context

    context = await get_evo_context()
    return context.file_transfers.resolve(file_path)
