# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""Base class and protocol for staged object types with discoverable interactions.

Each staged object type defines its own set of interactions (inspect, summarize,
plot, etc.) that can be lazily discovered and generically invoked. This avoids
hard-coding tool lists per type and enables a simple two-tool pattern:

1. ``stage_list_interactions`` — discover what you can do with an object type
2. ``stage_invoke_interaction`` — call an interaction by name on a staged object

Standalone object type modules register themselves with the
``staged_object_type_registry`` at import time. The registry also provides
lookups by Evo SDK class and data class, replacing the former
``DescriptorRegistry``.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Callable, Awaitable, ClassVar

from evo_mcp.staging.errors import StageValidationError

__all__ = [
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
        Machine-readable identifier (e.g. ``"summarize"``, ``"get_structure_details"``).
    display_name : str
        Human-readable label.
    description : str
        One-line explanation of what the interaction does.
    handler : async (payload, params) -> dict
        The async callable that executes the interaction.
        When ``params_model`` is set the handler receives a validated model
        instance; otherwise it receives the raw params dict.
    params_model : type | None
        Optional Pydantic ``BaseModel`` subclass. When set, incoming params are
        validated and coerced before the handler is called. The JSON Schema
        produced by the model is included in ``describe()`` output so LLMs can
        discover accepted fields.
    """

    name: str
    display_name: str
    description: str
    handler: Callable[[Any, Any], Awaitable[dict[str, Any]]]
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
    """Base class for a staged object type that exposes discoverable interactions.

    Every subclass **must** implement:
    - ``validate`` — raise ``StageValidationError`` if the payload is invalid.
    - ``summarize`` — return a lightweight summary dict for the ``StagedEnvelope``.
    - ``create`` — create a new staged object from validated params.
    - ``create_params_model`` — set to a Pydantic ``BaseModel`` class, or ``None``
      if the type does not support local creation.

    Optionally override:
    - ``from_dict`` — deserialize a fixture dict into a typed payload (for seeding).

    Class-level attributes for SDK integration:

    - ``evo_class`` — the SDK wrapper class (``Variogram``, ``PointSet``, ``BlockModel``).
    - ``data_classes`` — typed data classes accepted as staged payloads.
    - ``supported_publish_modes`` — subset of ``{"create", "new_version"}``.
    - ``fixture_path_segment`` — sub-folder under ``/fixtures/`` for dev seeding.
    - ``role_label`` / ``role_article`` — for error messages.
    - ``priority`` — higher-priority types are checked first in ``get_by_evo_class``
      when multiple types share the same ``evo_class``. Default is ``0``.
    """

    object_type: str = ""
    display_name: str = ""

    # SDK integration
    evo_class: type | None = None
    data_classes: tuple[type, ...] = ()
    supported_publish_modes: frozenset[str] = frozenset()
    fixture_path_segment: str = ""
    role_label: str = ""
    role_article: str = ""
    priority: int = 0

    # Set to a Pydantic BaseModel subclass to enable stage_create_object.
    # Set to None for import-only types (e.g. BlockModel).
    create_params_model: ClassVar[type | None] = None

    def __init__(self) -> None:
        self._interactions: dict[str, Interaction] = {}

    def validate(self, payload: Any) -> None:
        """Validate a payload: type-check against ``data_classes``, then domain rules.

        Raises ``StageValidationError`` if the payload is invalid.
        Called by the staging service before storing every payload.
        """
        if self.data_classes and not isinstance(payload, self.data_classes):
            expected = " or ".join(cls.__name__ for cls in self.data_classes)
            raise StageValidationError(
                f"Expected {expected}, got {type(payload).__name__}."
            )
        self._validate(payload)

    @abc.abstractmethod
    def _validate(self, payload: Any) -> None:
        """Type-specific validation rules (after the type-check passes).

        Override in subclasses to enforce domain constraints.
        """

    @abc.abstractmethod
    def summarize(self, payload: Any) -> dict[str, Any]:
        """Return a lightweight summary dict stored in the ``StagedEnvelope``.

        Keep this sync and cheap — it is called on every stage operation.
        """

    def from_dict(self, data: dict[str, Any]) -> Any:
        """Deserialize a fixture dict into a typed payload.

        Override in object types that support fixture seeding via ``dev_tools``.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support deserialization from dict."
        )

    @abc.abstractmethod
    async def create(self, params: Any) -> dict[str, Any]:
        """Create a new staged object from validated create params.

        ``params`` is an instance of ``create_params_model`` when set.
        Types that do not support local creation must raise ``NotImplementedError``.
        """

    # ── Import / publish hooks (override in subclasses) ───────────────────────

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
        raise NotImplementedError(
            f"{type(self).__name__} does not support publish_create."
        )

    async def publish_replace(self, context: Any, url: str, data: Any) -> Any:
        """SDK call for ``mode='new_version'``."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support publish_replace."
        )

    def import_guard(self, evo_obj: Any) -> bool:
        """Predicate for disambiguation when multiple types share ``evo_class``.

        Override together with setting ``priority > 0`` to ensure this type
        is checked before lower-priority types sharing the same ``evo_class``.
        """
        return True

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
            raise ValueError(
                f"Unknown interaction '{name}' on {self.display_name}. "
                f"Available: {available}"
            )
        return interaction

    async def invoke(
        self,
        name: str,
        payload: Any,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Invoke an interaction by name with the given payload and parameters.

        If the interaction declares a ``params_model``, the params dict is
        validated and coerced by the model before being passed to the handler.
        """
        interaction = self.get_interaction(name)
        if interaction.params_model is not None:
            validated = interaction.params_model.model_validate(params or {})
            return await interaction.handler(payload, validated)
        return await interaction.handler(payload, params or {})


class StagedObjectTypeRegistry:
    """Registry mapping object types to their StagedObjectType instances."""

    def __init__(self) -> None:
        self._types: dict[str, StagedObjectType] = {}

    def register(self, staged_type: StagedObjectType) -> None:
        self._types[staged_type.object_type] = staged_type

    def get(self, object_type: str) -> StagedObjectType | None:
        return self._types.get(object_type)

    def get_or_raise(self, object_type: str) -> StagedObjectType:
        result = self._types.get(object_type)
        if result is None:
            available = ", ".join(sorted(self._types.keys()))
            raise ValueError(
                f"No staged object type registered for '{object_type}'. "
                f"Available: {available}"
            )
        return result

    def get_by_evo_class(self, evo_obj: Any) -> StagedObjectType:
        """Find the type that matches an Evo SDK object.

        Types are checked in descending ``priority`` order. When priorities
        are equal the first match wins. Override ``import_guard`` on higher-
        priority types for fine-grained disambiguation.
        """
        candidates = [
            t
            for t in self._types.values()
            if t.evo_class is not None and isinstance(evo_obj, t.evo_class)
        ]
        if not candidates:
            raise ValueError(
                f"No type registered for Evo class '{type(evo_obj).__name__}'."
            )
        candidates.sort(key=lambda t: t.priority, reverse=True)
        for t in candidates:
            if t.import_guard(evo_obj):
                return t
        raise ValueError(
            f"No type matched for Evo class '{type(evo_obj).__name__}' "
            f"after import_guard checks."
        )

    def get_by_data_class(self, data: Any) -> StagedObjectType:
        """Find the type whose ``data_classes`` match a staged payload."""
        for obj_type in self._types.values():
            if obj_type.data_classes and isinstance(data, obj_type.data_classes):
                return obj_type
        raise ValueError(f"No type registered for data class '{type(data).__name__}'.")

    def all(self) -> list[StagedObjectType]:
        return list(self._types.values())


# Module-level singleton.
staged_object_type_registry = StagedObjectTypeRegistry()
