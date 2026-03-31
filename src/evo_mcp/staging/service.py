# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Staging service: centralized facade used by all tool modules.

A module-level singleton ``staging_service`` is provided for use by all
tool modules. Tool modules should import it as:

    from evo_mcp.staging.service import staging_service

"""

from __future__ import annotations

import uuid
from typing import Any

from evo_mcp.staging.codecs import get_codec
from evo_mcp.staging.models import ObjectType, StagedEnvelope, StageStatus
from evo_mcp.staging.store import MemoryStageStore, expires_iso, now_iso

__all__ = [
    "StagingService",
    "staging_service",
]


class StagingService:
    """Facade for all staging operations. Used by tool modules; never registered as an MCP tool."""

    def __init__(self, store: MemoryStageStore | None = None) -> None:
        self._store = store or MemoryStageStore()

    def stage_imported_object(
        self,
        object_type: ObjectType,
        typed_payload: Any,
        workspace_id: str | None,
        source_ref: dict[str, str | None],
    ) -> StagedEnvelope:
        """Stage a typed payload that was imported from Evo. Returns an envelope."""
        codec = get_codec(object_type)
        codec.validate(typed_payload)
        payload = codec.to_stage_payload(typed_payload)
        summary = codec.summarize(payload)
        stage_id = str(uuid.uuid4())
        ts = now_iso()
        envelope = StagedEnvelope(
            stage_id=stage_id,
            object_type=object_type,
            format_version="1.0",
            workspace_id=workspace_id,
            source_type="imported",
            source_ref=source_ref,
            summary=summary,
            status="active",
            payload_revision=1,
            created_at=ts,
            updated_at=ts,
            expires_at=expires_iso(self._store.ttl_seconds),
            size_hints={},
        )
        self._store.put(envelope, payload)
        return envelope

    def stage_local_build(
        self,
        object_type: ObjectType,
        typed_payload: Any,
        workspace_id: str | None = None,
        source_ref: dict[str, str | None] | None = None,
        ttl_seconds: int | None = None,
    ) -> StagedEnvelope:
        """Stage a typed payload that was built locally (CSV import, design tool, etc.)."""
        codec = get_codec(object_type)
        codec.validate(typed_payload)
        payload = codec.to_stage_payload(typed_payload)
        summary = codec.summarize(payload)
        stage_id = str(uuid.uuid4())
        ts = now_iso()
        effective_ttl = ttl_seconds if ttl_seconds is not None else self._store.ttl_seconds
        envelope = StagedEnvelope(
            stage_id=stage_id,
            object_type=object_type,
            format_version="1.0",
            workspace_id=workspace_id,
            source_type="built_local",
            source_ref=source_ref or {},
            summary=summary,
            status="active",
            payload_revision=1,
            created_at=ts,
            updated_at=ts,
            expires_at=expires_iso(effective_ttl),
            size_hints={},
        )
        self._store.put(envelope, payload)
        return envelope

    def get_stage_info(self, stage_id: str) -> StagedEnvelope:
        """Return the envelope for a stage (no payload)."""
        envelope, _ = self._store.get(stage_id)
        return envelope

    def get_stage_payload(self, stage_id: str) -> tuple[StagedEnvelope, Any]:
        """Return (envelope, typed_payload) for a stage."""
        return self._store.get(stage_id)

    def clone_stage(self, stage_id: str) -> StagedEnvelope:
        """Clone an active stage into a new stage with source_type='cloned'."""
        return self._store.clone(stage_id)

    def discard_stage(self, stage_id: str) -> None:
        """Mark a stage as discarded and release its payload."""
        self._store.discard(stage_id)

    def publish_stage(self, stage_id: str) -> tuple[StagedEnvelope, Any]:
        """Mark a stage as published and return the typed payload for SDK publish calls.

        The payload is removed from the store after this call.
        """
        envelope, payload = self._store.get(stage_id)
        published_envelope = self._store.mark_published(stage_id)
        return published_envelope, payload

    def list_stages(
        self,
        object_type: ObjectType | None = None,
        workspace_id: str | None = None,
        status: StageStatus | None = None,
        limit: int = 100,
    ) -> list[StagedEnvelope]:
        return self._store.list(
            object_type=object_type,
            workspace_id=workspace_id,
            status=status,
            limit=limit,
        )

    def gc_stages(self, dry_run: bool = True) -> dict[str, Any]:
        return self._store.gc(dry_run=dry_run)


# Module-level singleton shared by all tool modules.
staging_service = StagingService()
