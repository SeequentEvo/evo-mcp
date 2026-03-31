# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Object name resolver with case-insensitive matching and type scoping."""

from __future__ import annotations

from typing import Any

from evo_mcp.session.models import RegistryEntry
from evo_mcp.staging.models import ObjectType


class ResolutionError(Exception):
    """Raised when an object reference cannot be resolved unambiguously."""


class ObjectResolver:
    """Resolves user-provided names to registry entries.

    Resolution strategy (in order):
    1. Exact name + type match
    2. Case-insensitive name + type match
    3. Exact name (any type) — if unambiguous
    4. Case-insensitive name (any type) — if unambiguous
    5. Latest object of the requested type (when name is None)
    """

    def resolve(
        self,
        entries: dict[str, RegistryEntry],
        name: str | None = None,
        object_type: ObjectType | None = None,
    ) -> RegistryEntry:
        """Resolve a single registry entry from a name and/or type.

        Args:
            entries: All registry entries keyed by internal key.
            name: User-provided object name (optional if type is given).
            object_type: Expected object type (optional if name is given).

        Returns:
            The resolved RegistryEntry.

        Raises:
            ResolutionError: If the reference is ambiguous or not found.
        """
        if name is None and object_type is None:
            raise ResolutionError(
                "Provide an object name or type to resolve a reference."
            )

        candidates = list(entries.values())

        if name is None:
            return self._resolve_latest_by_type(candidates, object_type)

        # 1. Exact name + type
        if object_type is not None:
            exact = [
                e for e in candidates
                if e.name == name and e.object_type == object_type
            ]
            if len(exact) == 1:
                return exact[0]
            if len(exact) > 1:
                return self._pick_latest(exact)

        # 2. Exact name (any type)
        exact_any = [e for e in candidates if e.name == name]
        if object_type is not None:
            exact_any = [e for e in exact_any if e.object_type == object_type]
        if len(exact_any) == 1:
            return exact_any[0]
        if len(exact_any) > 1:
            if object_type is not None:
                return self._pick_latest(exact_any)
            types_found = {e.object_type for e in exact_any}
            if len(types_found) == 1:
                return self._pick_latest(exact_any)
            raise ResolutionError(
                f"Ambiguous name '{name}' matches multiple types: "
                f"{', '.join(sorted(types_found))}. Specify the object type."
            )

        # 3. Case-insensitive match
        name_lower = name.lower()
        ci_matches = [e for e in candidates if e.name.lower() == name_lower]
        if object_type is not None:
            ci_matches = [e for e in ci_matches if e.object_type == object_type]
        if len(ci_matches) == 1:
            return ci_matches[0]
        if len(ci_matches) > 1:
            if object_type is not None:
                return self._pick_latest(ci_matches)
            types_found = {e.object_type for e in ci_matches}
            if len(types_found) == 1:
                return self._pick_latest(ci_matches)
            raise ResolutionError(
                f"Ambiguous name '{name}' matches multiple types: "
                f"{', '.join(sorted(types_found))}. Specify the object type."
            )

        # Nothing found
        available = sorted({e.name for e in candidates})
        hint = f" Available objects: {', '.join(available)}" if available else ""
        type_hint = f" (type={object_type})" if object_type else ""
        raise ResolutionError(
            f"No object found with name '{name}'{type_hint}.{hint}"
        )

    def _resolve_latest_by_type(
        self,
        candidates: list[RegistryEntry],
        object_type: ObjectType,
    ) -> RegistryEntry:
        """Return the most recently registered object of the given type."""
        typed = [e for e in candidates if e.object_type == object_type]
        if not typed:
            raise ResolutionError(
                f"No {object_type} objects in the current session."
            )
        return self._pick_latest(typed)

    @staticmethod
    def _pick_latest(entries: list[RegistryEntry]) -> RegistryEntry:
        """Pick the entry with the latest created_at timestamp."""
        return max(entries, key=lambda e: e.created_at)
