# Estimation workflow design

End-to-end design for how an estimation workflow (e.g. kriging) is orchestrated
across **MCP Tools → Session → Staging → Evo**. Covers the key layers,
their responsibilities, and the design decisions that connect them.

## Workflow stack

```mermaid
flowchart TB
    subgraph MCP["MCP Tools Layer  (tools/)"]
        ST[object_staging_tools]
        CT[compute_tools]
        DT[dev_tools 🔒]
    end

    subgraph Session["session/  — Name Registry"]
        OR[ObjectRegistry\nname → stage_id]
    end

    subgraph Staging["staging/  — Payload Store"]
        SS[StagingService]
        OT[Object Types\nvariogram · point_set\nblock_model · search_neighborhood]
    end

    subgraph Evo["Evo Platform"]
        WS[Workspaces / Objects]
        COMP[Compute Service]
    end

    ST -->|name-based| Session
    Session -->|stage_id| Staging
    CT & ST -->|SDK calls| Evo
```

---

## Core principle

> Users and LLMs always work with **object names** — never internal IDs, stage IDs, or tool mechanics.

```
User: "inspect my CU variogram"
  → ObjectRegistry.resolve("CU variogram")
  → StagingService.get_stage_payload(stage_id)
  → StagedObjectType.invoke("summarize", payload)
  → plain-language result
```

---

## Key design decisions

| Decision | Why |
|---|---|
| Name-based registry over raw IDs | LLMs/users work in geoscience language, not UUIDs |
| Plugin object types (self-registering) | Add a new type without touching tool code |
| Two-tool interaction pattern | Capabilities are discoverable, not hard-coded |
