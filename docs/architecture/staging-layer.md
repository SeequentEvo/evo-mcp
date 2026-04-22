# Staging Layer — `evo_mcp/staging/`

Typed, in-memory payload store with TTL, size guards, and a **plugin system** for object types.

---

## Structure

```
staging/
  service.py     StagingService — combined store + facade (singleton)
  models.py      StagedEnvelope — metadata (no payload exposed)
  errors.py      StageError hierarchy
  runtime.py     DI shim — breaks circular import with session/
  helpers.py     Shared Pydantic geometry schemas
  objects/
    base.py      StagedObjectType + Interaction + StagedObjectTypeRegistry
    variogram.py · point_set.py · block_model.py
    regular_block_model.py · search_neighborhood.py
```

---

## Plugin Object Type

Every object type is a self-registering subclass of `StagedObjectType`:

```mermaid
classDiagram
    class StagedObjectType {
        <<abstract>>
        object_type: str
        evo_class: type
        data_class: type
        create_params_model: type
        supported_publish_modes: frozenset
        validate(payload)
        summarize(payload) → dict
        create(params) → dict
        import_handler(obj, ctx)
        publish_create / publish_replace
        list_interactions() → list
        invoke(name, payload, params) → dict
    }
    StagedObjectType <|-- VariogramType
    StagedObjectType <|-- PointSetType
    StagedObjectType <|-- BlockModelType
    StagedObjectType <|-- RegularBlockModelType
    StagedObjectType <|-- SearchNeighborhoodType
```

Adding a new object type = add one subclass file. No changes to tools needed.

---

## Circular Import Prevention

```mermaid
flowchart LR
    OBJ["staging.objects.*\n(needs session registry)"]
    RT["staging.runtime\n_registry = None\n← wired at startup"]
    SES["session.registry\n(imports staging.service)"]

    OBJ -->|get_registry()| RT
    RT -.->|configure() at startup| SES

    style RT fill:#fffbe6,stroke:#d4b800
```

`staging/runtime.py` is a leaf module — no runtime imports — preventing the
`staging.objects` ↔ `session.registry` circular dependency.
