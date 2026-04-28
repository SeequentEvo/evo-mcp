# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Base class and protocol for staged object types with discoverable interactions.

Each staged object type defines its own set of interactions (inspect, summarize,
plot, etc.) that can be lazily discovered and generically invoked. This avoids
hard-coding tool lists per type and enables a simple two-tool pattern:

1. ``stage_list_interactions`` — discover what you can do with an object type
2. ``stage_invoke_interaction`` — call an interaction by name on a staged object

Two base classes are provided:

- ``StagedObjectType`` — minimal base for any locally-staged object type.
- ``EvoStagedObjectType`` — extends the base for types that integrate with the
  Evo SDK (import from Evo, publish to Evo).

Standalone object type modules register themselves with the
``staged_object_type_registry`` at import time.
"""

import abc
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from evo_mcp.staging.errors import StageValidationError
from evo_mcp.staging.runtime import get_registry

__all__ = [
    "EvoStagedObjectType",
    "Interaction",
    "StagedObjectType",
    "StagedObjectTypeRegistry",
    "staged_object_type_registry",
]


@dataclass(frozen=True)
class Interaction:
    """Describes a single interaction available on a staged object type.

    Parameters
    ----------
    name : str
        Machine-readable identifier (e.g. ``"get_summary"``, ``"get_structure_details"``).
    display_name : str
        Human-readable label.
    description : str
        One-line explanation of what the interaction does.
    handler : async callable
        The async callable that executes the interaction.
    params_model : type | None
        Optional Pydantic ``BaseModel`` subclass for validated input parameters.
        The JSON Schema is included in ``describe()`` output for LLM discovery.
    """

    name: str
    display_name: str
    description: str
    handler: Callable[..., Awaitable[dict[str, Any]]]
    params_model: type | None = None

    def describe(self) -> dict[str, Any]:
        """Return a JSON-serializable description for tool discovery."""
        result: dict[str, Any] = {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
        }
        if self.params_model is not None:
            result["parameters_schema"] = self.params_model.model_json_schema()
        return result


class StagedObjectType(abc.ABC):
    """Base class for a staged object type with discoverable interactions.

    Covers the minimal contract for any locally-staged object — no Evo SDK
    knowledge required. Types that can import from or publish to Evo should
    inherit ``EvoStagedObjectType`` instead.

    Every subclass **must** implement:
    - ``summarize`` — return a lightweight summary dict for the ``StagedEnvelope``.

    Optionally override:
    - ``_validate`` — raise ``StageValidationError`` for domain-level payload
      constraints (called after the data_class type-check by ``validate``).
    - ``from_dict`` — deserialize a fixture dict into a typed payload.

    Create interactions are registered in ``__init__`` via ``_register_interaction``.
    """

    object_type: str = ""
    display_name: str = ""
    data_class: type | None = None

    def __init__(self) -> None:
        self._interactions: dict[str, Interaction] = {}

    def validate(self, payload: Any) -> None:
        """Validate a payload: type-check against ``data_class``, then domain rules."""
        if self.data_class is not None and not isinstance(payload, self.data_class):
            raise StageValidationError(f"Expected {self.data_class.__name__}, got {type(payload).__name__}.")
        self._validate(payload)

    def _validate(self, payload: Any) -> None:
        """Type-specific validation rules. Override in subclasses."""
        pass

    @abc.abstractmethod
    def summarize(self, payload: Any) -> dict[str, Any]:
        """Return a lightweight summary dict stored in the ``StagedEnvelope``."""

    def from_dict(self, data: dict[str, Any]) -> Any:
        """Deserialize a fixture dict into a typed payload (for dev seeding)."""
        raise NotImplementedError(f"{type(self).__name__} does not support deserialization from dict.")

    async def create(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Create a new staged object of this type. Override in subclasses."""
        raise NotImplementedError(f"{type(self).__name__} does not support create.")

    # ── Interaction discovery & dispatch ───────────────────────────────────────

    def _register_interaction(self, interaction: Interaction) -> None:
        self._interactions[interaction.name] = interaction

    def list_interactions(self) -> list[dict[str, Any]]:
        """Return JSON-serializable descriptions of all registered interactions."""
        return [interaction.describe() for interaction in self._interactions.values()]

    def get_interaction(self, name: str) -> Interaction:
        """Look up an interaction by name. Raises ValueError if not found."""
        interaction = self._interactions.get(name)
        if interaction is None:
            available = ", ".join(sorted(self._interactions.keys()))
            raise ValueError(f"Unknown interaction '{name}' on {self.display_name}. Available: {available}")
        return interaction

    async def _dispatch(
        self,
        interaction: Interaction,
        payload: Any,
        params: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate params and call the interaction handler with the staged payload."""
        if interaction.params_model is not None:
            validated = interaction.params_model.model_validate(params or {})
            return await interaction.handler(payload, validated)
        return await interaction.handler(payload)

    async def invoke(
        self,
        name: str,
        object_name: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke an interaction by name on a staged object.

        The payload is fetched internally from the registry using ``object_name``.
        """
        _, payload = get_registry().get_payload(name=object_name, object_type=self.object_type)
        return await self._dispatch(self.get_interaction(name), payload, params)


class EvoStagedObjectType(StagedObjectType):
    """Staged object type with Evo SDK integration (import and/or publish).

    Extends ``StagedObjectType`` with the properties and hooks needed to move
    objects between the local staging area and Evo:

    - ``evo_class`` — the SDK wrapper class used to match imported objects
      (e.g. ``Variogram``, ``PointSet``, ``BlockModel``). Set to ``None``
      for locally-created types that can only be published, not imported.
    - ``supported_publish_modes`` — subset of ``{"create", "new_version"}``.
    """

    evo_class: type | None = None
    supported_publish_modes: frozenset[str] = frozenset()

    async def import_handler(
        self,
        obj: Any,
        context: Any,
    ) -> tuple[Any, dict[str, Any], str]:
        """Convert an Evo SDK object into a typed data payload for staging.

        Returns ``(data, source_ref_extras, message)``.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support import.")

    async def publish_create(self, context: Any, data: Any, path: str) -> Any:
        """SDK call for ``mode='create'``."""
        raise NotImplementedError(f"{type(self).__name__} does not support publish_create.")

    async def publish_replace(self, context: Any, url: str, data: Any) -> Any:
        """SDK call for ``mode='new_version'``."""
        raise NotImplementedError(f"{type(self).__name__} does not support publish_replace.")


class StagedObjectTypeRegistry:
    """Registry mapping object type identifiers to their ``StagedObjectType`` instances."""

    def __init__(self) -> None:
        self._types: dict[str, StagedObjectType] = {}

    def register(self, staged_type: StagedObjectType) -> None:
        if not staged_type.object_type:
            raise ValueError(f"{type(staged_type).__name__}.object_type must not be empty.")
        self._types[staged_type.object_type] = staged_type

    def get(self, object_type: str) -> StagedObjectType:
        result = self._types.get(object_type)
        if result is None:
            available = ", ".join(sorted(self._types.keys()))
            raise ValueError(f"No staged object type registered for '{object_type}'. Available: {available}")
        return result

    def all(self) -> list[StagedObjectType]:
        return list(self._types.values())


# Module-level singleton.
staged_object_type_registry = StagedObjectTypeRegistry()
