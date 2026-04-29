# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Staging-specific error hierarchy. Tool layer maps these to ValueError messages."""

__all__ = [
    "StageCapacityError",
    "StageError",
    "StageExpiredError",
    "StageNotFoundError",
    "StageValidationError",
]


class StageError(Exception):
    """Base error for all staging operations."""


class StageNotFoundError(StageError):
    """Raised when a stage_id cannot be found in the store."""

    def __init__(self, stage_id: str) -> None:
        super().__init__(f"Stage not found: {stage_id!r}")
        self.stage_id = stage_id


class StageExpiredError(StageError):
    """Raised when a stage has passed its TTL and is no longer accessible."""

    def __init__(self, stage_id: str) -> None:
        super().__init__(f"Stage has expired: {stage_id!r}")
        self.stage_id = stage_id


class StageValidationError(StageError):
    """Raised when a staged payload fails type or schema validation."""


class StageCapacityError(StageError):
    """Raised when store capacity limits are exceeded."""
