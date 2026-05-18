# The two-tool interaction pattern

Instead of one MCP tool per capability per type, **all domain actions go through two generic tools**.

```mermaid
flowchart LR
    subgraph DISCOVER["Step 1 — Discover"]
        T1["staging_list_interactions\nobject_type='variogram'"]
        OUT1["get_summary\nget_structure_details\nget_search_parameters\nget_ellipsoid_details\nget_curve_details"]
        T1 -->|"returns available actions\n+ param schemas"| OUT1
    end

    subgraph INVOKE["Step 2 — Invoke"]
        T2["staging_invoke_interaction\nobject_name='CU variogram'\ninteraction_name='get_curve_details'\nparams={n_points:200}"]
        OT["VariogramObjectType\n.invoke('get_curve_details', payload, params)"]
        OUT2["{ x_values, y_values,\nsill, nugget,\nprincipal directions }"]
        T2 --> OT --> OUT2
    end

    DISCOVER -->|"LLM picks action"| INVOKE
```

---

## Adding a new capability

**It's not necessary to create a new MCP tool.** Instead, add one `Interaction` inside the object type module:

```python
self._register_interaction(Interaction(
    name="export_to_csv",
    display_name="Export to CSV",
    description="Serialise variogram to CSV-compatible dict.",
    handler=self._export_to_csv,
    params_model=ExportParams,   # optional — Pydantic schema auto-discovered by LLM
))
```