# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""In-memory staging store backend with TTL and capacity guardrails.

This is the sole backend for initial implementation. A durable backend
(sqlite/redis) can be swapped in later by replacing this module.
"""

import copy
import sys
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Any

from evo_mcp.staging.errors import (
    StageCapacityError,
    StageExpiredError,
    StageNotFoundError,
    StageRevisionConflictError,
    StageValidationError,
)
from evo_mcp.staging.models import ObjectType, StagedEnvelope, StageStatus

_DEFAULT_TTL_SECONDS = 3600
_DEFAULT_MAX_ACTIVE = 200
_DEFAULT_MAX_PAYLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

__all__ = [
    "MemoryStageStore",
    "now_iso",
    "expires_iso",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def expires_iso(ttl_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


def _parse_iso(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class MemoryStageStore:
    """Thread-unsafe in-memory store. Suitable for single-process MCP server deployments."""

    def __init__(
        self,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_active: int = _DEFAULT_MAX_ACTIVE,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_active = max_active
        self._envelopes: dict[str, StagedEnvelope] = {}
        self._payloads: dict[str, Any] = {}

    @property
    def ttl_seconds(self) -> int:
        """Public access to the store's TTL setting."""
        return self._ttl_seconds

    def _active_count(self) -> int:
        return sum(1 for e in self._envelopes.values() if e.status == "active")

    def _check_expiry(self, envelope: StagedEnvelope) -> StagedEnvelope:
        if envelope.status == "expired":
            raise StageExpiredError(envelope.stage_id)
        now = datetime.now(timezone.utc)
        expires = _parse_iso(envelope.expires_at)
        if now >= expires:
            updated = replace(envelope, status="expired", updated_at=now_iso())
            self._envelopes[envelope.stage_id] = updated
            raise StageExpiredError(envelope.stage_id)
        return envelope

    def _estimate_payload_bytes(self, payload: Any) -> int:
        """Estimate real memory footprint of a payload, not just shallow object size."""
        # For DataFrame-backed payloads (PointSetData, etc.), use deep memory usage
        if hasattr(payload, "locations") and hasattr(payload.locations, "memory_usage"):
            return int(payload.locations.memory_usage(deep=True).sum())
        # For pydantic/dataclass models with a __dict__, recurse shallowly
        if hasattr(payload, "__dict__"):
            return sum(sys.getsizeof(v) for v in payload.__dict__.values())
        return sys.getsizeof(payload)

    def _check_payload_size(self, payload: Any) -> None:
        """Raise StageValidationError if payload exceeds the size limit."""
        estimated = self._estimate_payload_bytes(payload)
        if estimated > _DEFAULT_MAX_PAYLOAD_BYTES:
            raise StageValidationError(
                f"Payload size (~{estimated:,} bytes) exceeds maximum of "
                f"{_DEFAULT_MAX_PAYLOAD_BYTES:,} bytes."
            )

    def put(self, envelope: StagedEnvelope, payload: Any) -> str:
        self._check_payload_size(payload)
        if self._active_count() >= self._max_active:
            raise StageCapacityError(
                f"Active stage limit ({self._max_active}) reached. "
                "Discard or publish existing stages first."
            )
        self._envelopes[envelope.stage_id] = envelope
        self._payloads[envelope.stage_id] = payload
        return envelope.stage_id

    def get(self, stage_id: str) -> tuple[StagedEnvelope, Any]:
        envelope = self._envelopes.get(stage_id)
        if envelope is None:
            raise StageNotFoundError(stage_id)
        if envelope.status in ("discarded", "published"):
            raise StageNotFoundError(stage_id)
        envelope = self._check_expiry(envelope)
        return envelope, self._payloads[stage_id]

    def update(
        self,
        stage_id: str,
        payload: Any,
        expected_revision: int | None = None,
    ) -> StagedEnvelope:
        envelope, _ = self.get(stage_id)
        self._check_payload_size(payload)
        if (
            expected_revision is not None
            and envelope.payload_revision != expected_revision
        ):
            raise StageRevisionConflictError(
                stage_id, expected_revision, envelope.payload_revision
            )
        updated = replace(
            envelope,
            source_type="mutated",
            payload_revision=envelope.payload_revision + 1,
            updated_at=now_iso(),
        )
        self._envelopes[stage_id] = updated
        self._payloads[stage_id] = payload
        return updated

    def clone(self, stage_id: str) -> StagedEnvelope:
        envelope, payload = self.get(stage_id)
        new_id = str(uuid.uuid4())
        now = now_iso()
        cloned = StagedEnvelope(
            stage_id=new_id,
            object_type=envelope.object_type,
            format_version=envelope.format_version,
            workspace_id=envelope.workspace_id,
            source_type="cloned",
            source_ref={**envelope.source_ref, "cloned_from": stage_id},
            summary=copy.deepcopy(envelope.summary),
            status="active",
            payload_revision=1,
            created_at=now,
            updated_at=now,
            expires_at=expires_iso(self._ttl_seconds),
            size_hints=copy.deepcopy(envelope.size_hints),
        )
        self._envelopes[new_id] = cloned
        self._payloads[new_id] = copy.deepcopy(payload)
        return cloned

    def discard(self, stage_id: str) -> None:
        envelope = self._envelopes.get(stage_id)
        if envelope is None:
            raise StageNotFoundError(stage_id)
        self._check_expiry(envelope)
        self._envelopes[stage_id] = replace(
            envelope, status="discarded", updated_at=now_iso()
        )
        self._payloads.pop(stage_id, None)

    def mark_published(self, stage_id: str) -> StagedEnvelope:
        envelope = self._envelopes.get(stage_id)
        if envelope is None:
            raise StageNotFoundError(stage_id)
        self._check_expiry(envelope)
        updated = replace(envelope, status="published", updated_at=now_iso())
        self._envelopes[stage_id] = updated
        self._payloads.pop(stage_id, None)
        return updated

    def list(
        self,
        object_type: ObjectType | None = None,
        workspace_id: str | None = None,
        status: StageStatus | None = None,
        limit: int = 100,
    ) -> list[StagedEnvelope]:
        results = []
        now_dt = datetime.now(timezone.utc)
        for envelope in list(self._envelopes.values()):
            if (
                envelope.status == "active"
                and _parse_iso(envelope.expires_at) <= now_dt
            ):
                envelope = replace(envelope, status="expired", updated_at=now_iso())
                self._envelopes[envelope.stage_id] = envelope
            if object_type is not None and envelope.object_type != object_type:
                continue
            if workspace_id is not None and envelope.workspace_id != workspace_id:
                continue
            if status is not None and envelope.status != status:
                continue
            results.append(envelope)
            if len(results) >= limit:
                break
        return results

    def gc(
        self,
        now: str | None = None,
        dry_run: bool = True,
    ) -> dict[str, Any]:
        now_dt = datetime.fromisoformat(now) if now else datetime.now(timezone.utc)
        if now_dt.tzinfo is None:
            now_dt = now_dt.replace(tzinfo=timezone.utc)
        to_remove = []
        for stage_id, envelope in self._envelopes.items():
            if envelope.status in ("discarded", "published"):
                to_remove.append(stage_id)
            elif (
                envelope.status == "active"
                and _parse_iso(envelope.expires_at) <= now_dt
            ):
                to_remove.append(stage_id)
        if not dry_run:
            for stage_id in to_remove:
                self._envelopes.pop(stage_id, None)
                self._payloads.pop(stage_id, None)
        return {"removed": len(to_remove), "stage_ids": to_remove, "dry_run": dry_run}
