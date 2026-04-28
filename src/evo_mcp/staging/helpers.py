# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Shared helpers for staging object modules.

Provides:
- Pydantic geometry schemas: ``Point3Schema``, ``Size3iSchema``,
  ``Size3dSchema``, ``RotationSchema`` — validate dicts into SDK types
- Bounding-box helper: ``_bbox_dict``
"""

from evo.common.typed import BoundingBox
from evo.objects.typed import Point3, Rotation, Size3d, Size3i
from pydantic import BaseModel, ConfigDict

__all__ = [
    "Point3Schema",
    "RotationSchema",
    "Size3dSchema",
    "Size3iSchema",
    "_bbox_dict",
]


# ── Pydantic geometry schemas ─────────────────────────────────────────────────


class Point3Schema(BaseModel):
    """Validates a dict and constructs an SDK ``Point3(x, y, z)``."""

    model_config = ConfigDict(extra="forbid")
    x: float
    y: float
    z: float

    def to_sdk(self) -> Point3:
        return Point3(x=self.x, y=self.y, z=self.z)


class Size3iSchema(BaseModel):
    """Validates a dict and constructs an SDK ``Size3i(nx, ny, nz)``."""

    model_config = ConfigDict(extra="forbid")
    nx: int
    ny: int
    nz: int

    def to_sdk(self) -> Size3i:
        return Size3i(nx=self.nx, ny=self.ny, nz=self.nz)


class Size3dSchema(BaseModel):
    """Validates a dict and constructs an SDK ``Size3d(dx, dy, dz)``."""

    model_config = ConfigDict(extra="forbid")
    dx: float
    dy: float
    dz: float

    def to_sdk(self) -> Size3d:
        return Size3d(dx=self.dx, dy=self.dy, dz=self.dz)


class RotationSchema(BaseModel):
    """Validates a dict and constructs an SDK ``Rotation``."""

    model_config = ConfigDict(extra="forbid")
    dip_azimuth: float = 0.0
    dip: float = 0.0
    pitch: float = 0.0

    def to_sdk(self) -> "Rotation":
        return Rotation(dip_azimuth=self.dip_azimuth, dip=self.dip, pitch=self.pitch)


def _bbox_dict(bbox: BoundingBox) -> dict[str, float]:
    """Convert an SDK BoundingBox to a plain dict."""
    return {
        "x_min": float(bbox.x_min),
        "x_max": float(bbox.x_max),
        "y_min": float(bbox.y_min),
        "y_max": float(bbox.y_max),
        "z_min": float(bbox.z_min),
        "z_max": float(bbox.z_max),
    }
