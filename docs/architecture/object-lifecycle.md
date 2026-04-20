# Object Staging Lifecycle

## States

```mermaid
stateDiagram-v2
    [*] --> active : create / import
    active --> active : inspect / invoke interactions
    active --> published : staging_publish_object
    active --> discarded : staging_discard_object
    active --> expired : TTL exceeded (1 hour)
    published --> [*]
    discarded --> [*]
    expired --> [*]
```

---

## Entry — Create or Import

```mermaid
flowchart LR
    A["staging_create_object\n(local build)"] --> S[StagingService]
    B["staging_import_object\n(from Evo UUID)"] --> S
    S --> R[ObjectRegistry\nname → stage_id]
```

- **Create:** Pydantic params validated → `StagedObjectType.create()` → staged locally
- **Import:** SDK object fetched from Evo → `import_handler()` converts to typed data → staged

---

## Use — Inspect / Validate

```mermaid
flowchart LR
    A["staging_invoke_interaction\n(inspect, plot, summarize...)"] --> R[ObjectRegistry]
    B["staging_spatial_validation\n(CRS check — no API call)"] --> R
    R --> SS[StagingService\npayload]
```

---

## Exit — Publish or Discard

```mermaid
flowchart LR
    A["staging_publish_object\nmode: create | new_version"] --> EVO[Evo Platform]
    B["staging_discard_object"] --> DEL[removed from session]
    A --> REG[mark_published in registry]
```

