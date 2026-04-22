# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Staging service: centralized facade used by all tool modules.

Combines what was previously split across ``StagingService`` and
``MemoryStageStore`` into a single class. A module-level singleton
``staging_service`` is provided for use by all tool modules::

    from evo_mcp.staging.service import staging_service

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
    StageValidationError,
)
from evo_mcp.staging.models import ObjectType, SourceType, StagedEnvelope, StageStatus
from evo_mcp.staging.objects import staged_object_type_registry

__all__ = [
    "StagingService",
    "now_iso",
    "staging_service",
]

_DEFAULT_TTL_SECONDS = 3600
_DEFAULT_MAX_ACTIVE = 200
_DEFAULT_MAX_PAYLOAD_BYTES = 50 * 1024 * 1024  # 50 MB


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expires_iso(ttl_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


def _parse_iso(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


class StagingService:
    """Combined staging service and in-memory store.

    Suitable for single-process MCP server deployments.
    A durable backend (sqlite/redis) can be swapped in later by replacing
    the private storage methods.
    """

    def __init__(
        self,
        ttl_seconds: int = _DEFAULT_TTL_SECONDS,
        max_active: int = _DEFAULT_MAX_ACTIVE,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_active = max_active
        self._envelopes: dict[str, StagedEnvelope] = {}
        self._payloads: dict[str, Any] = {}

    # ── Public staging API ──────────────────────────────────────────────────

    def stage(
        self,
        object_type: ObjectType,
        typed_payload: Any,
        *,
        source_type: SourceType,
        workspace_id: str | None = None,
        source_ref: dict[str, str | None] | None = None,
        ttl_seconds: int | None = None,
    ) -> StagedEnvelope:
        """Stage a typed payload and return its envelope.

        Validates and summarizes the payload via the object type.

        Parameters
        ----------
        object_type:
            Registered object type string (e.g. ``"variogram"``).
        typed_payload:
            The domain data object to stage.
        source_type:
            How the payload was produced (``"imported"``, ``"built_local"``, etc.).
        workspace_id:
            Associated workspace UUID, if any.
        source_ref:
            Provenance metadata (object_id, path, etc.).
        ttl_seconds:
            Override the default TTL for this stage.
        """
        obj_type = staged_object_type_registry.get_or_raise(object_type)
        obj_type.validate(typed_payload)
        summary = obj_type.summarize(typed_payload)

        stage_id = str(uuid.uuid4())
        ts = now_iso()
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._ttl_seconds
        envelope = StagedEnvelope(
            stage_id=stage_id,
            object_type=object_type,
            workspace_id=workspace_id,
            source_type=source_type,
            source_ref=source_ref or {},
            summary=summary,
            status="active",
            payload_revision=1,
            created_at=ts,
            updated_at=ts,
            expires_at=_expires_iso(effective_ttl),
        )
        self._put(envelope, typed_payload)
        return envelope

    # Convenience aliases kept for clarity at call sites
    def stage_imported_object(
        self,
        object_type: ObjectType,
        typed_payload: Any,
        workspace_id: str | None,
        source_ref: dict[str, str | None],
    ) -> StagedEnvelope:
        return self.stage(
            object_type,
            typed_payload,
            source_type="imported",
            workspace_id=workspace_id,
            source_ref=source_ref,
        )

    def stage_local_build(
        self,
        object_type: ObjectType,
        typed_payload: Any,
        workspace_id: str | None = None,
        source_ref: dict[str, str | None] | None = None,
        ttl_seconds: int | None = None,
    ) -> StagedEnvelope:
        return self.stage(
            object_type,
            typed_payload,
            source_type="built_local",
            workspace_id=workspace_id,
            source_ref=source_ref,
            ttl_seconds=ttl_seconds,
        )

    def get_stage_info(self, stage_id: str) -> StagedEnvelope:
        """Return the envelope for a stage (no payload)."""
        envelope, _ = self._get(stage_id)
        return envelope

    def get_stage_payload(self, stage_id: str) -> tuple[StagedEnvelope, Any]:
        """Return (envelope, typed_payload) for a stage."""
        return self._get(stage_id)

    def clone_stage(self, stage_id: str) -> StagedEnvelope:
        """Clone an active stage into a new stage with source_type='cloned'."""
        envelope, payload = self._get(stage_id)
        new_id = str(uuid.uuid4())
        now = now_iso()
        cloned = StagedEnvelope(
            stage_id=new_id,
            object_type=envelope.object_type,
            workspace_id=envelope.workspace_id,
            source_type="cloned",
            source_ref={**envelope.source_ref, "cloned_from": stage_id},
            summary=copy.deepcopy(envelope.summary),
            status="active",
            payload_revision=1,
            created_at=now,
            updated_at=now,
            expires_at=_expires_iso(self._ttl_seconds),
        )
        self._envelopes[new_id] = cloned
        self._payloads[new_id] = copy.deepcopy(payload)
        return cloned

    def discard_stage(self, stage_id: str) -> None:
        """Mark a stage as discarded and release its payload."""
        envelope = self._envelopes.get(stage_id)
        if envelope is None:
            raise StageNotFoundError(stage_id)
        self._check_expiry(envelope)
        self._envelopes[stage_id] = replace(envelope, status="discarded", updated_at=now_iso())
        self._payloads.pop(stage_id, None)

    def publish_stage(self, stage_id: str) -> tuple[StagedEnvelope, Any]:
        """Mark a stage as published and return the typed payload.

        The payload is removed from the store after this call.
        """
        envelope, payload = self._get(stage_id)
        updated = replace(envelope, status="published", updated_at=now_iso())
        self._envelopes[stage_id] = updated
        self._payloads.pop(stage_id, None)
        return updated, payload

    def list_stages(
        self,
        object_type: ObjectType | None = None,
        workspace_id: str | None = None,
        status: StageStatus | None = None,
        limit: int = 100,
    ) -> list[StagedEnvelope]:
        results = []
        now_dt = datetime.now(timezone.utc)
        for envelope in list(self._envelopes.values()):
            if envelope.status == "active" and _parse_iso(envelope.expires_at) <= now_dt:
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

    def gc_stages(self, dry_run: bool = True) -> dict[str, Any]:
        now_dt = datetime.now(timezone.utc)
        to_remove = []
        for stage_id, envelope in self._envelopes.items():
            if envelope.status in ("discarded", "published"):
                to_remove.append(stage_id)
            elif envelope.status == "active" and _parse_iso(envelope.expires_at) <= now_dt:
                to_remove.append(stage_id)
        if not dry_run:
            for stage_id in to_remove:
                self._envelopes.pop(stage_id, None)
                self._payloads.pop(stage_id, None)
        return {"removed": len(to_remove), "stage_ids": to_remove, "dry_run": dry_run}

    # ── Internal storage helpers ───────────────────────────────────────────

    def _active_count(self) -> int:
        return sum(1 for e in self._envelopes.values() if e.status == "active")

    def _estimate_payload_bytes(self, payload: Any) -> int:
        if hasattr(payload, "locations") and hasattr(payload.locations, "memory_usage"):
            return int(payload.locations.memory_usage(deep=True).sum())
        if hasattr(payload, "__dict__"):
            return sum(sys.getsizeof(v) for v in payload.__dict__.values())
        return sys.getsizeof(payload)

    def _check_payload_size(self, payload: Any) -> None:
        estimated = self._estimate_payload_bytes(payload)
        if estimated > _DEFAULT_MAX_PAYLOAD_BYTES:
            raise StageValidationError(
                f"Payload size (~{estimated:,} bytes) exceeds maximum of {_DEFAULT_MAX_PAYLOAD_BYTES:,} bytes."
            )

    def _check_expiry(self, envelope: StagedEnvelope) -> StagedEnvelope:
        if envelope.status == "expired":
            raise StageExpiredError(envelope.stage_id)
        if envelope.status in ("discarded", "published"):
            raise StageNotFoundError(envelope.stage_id)
        now = datetime.now(timezone.utc)
        if now >= _parse_iso(envelope.expires_at):
            updated = replace(envelope, status="expired", updated_at=now_iso())
            self._envelopes[envelope.stage_id] = updated
            raise StageExpiredError(envelope.stage_id)
        return envelope

    def _put(self, envelope: StagedEnvelope, payload: Any) -> None:
        self._check_payload_size(payload)
        if self._active_count() >= self._max_active:
            raise StageCapacityError(
                f"Active stage limit ({self._max_active}) reached. Discard or publish existing stages first."
            )
        self._envelopes[envelope.stage_id] = envelope
        self._payloads[envelope.stage_id] = payload

    def _get(self, stage_id: str) -> tuple[StagedEnvelope, Any]:
        envelope = self._envelopes.get(stage_id)
        if envelope is None:
            raise StageNotFoundError(stage_id)
        if envelope.status in ("discarded", "published"):
            raise StageNotFoundError(stage_id)
        envelope = self._check_expiry(envelope)
        return envelope, self._payloads[stage_id]


# Module-level singleton shared by all tool modules.
staging_service = StagingService()
