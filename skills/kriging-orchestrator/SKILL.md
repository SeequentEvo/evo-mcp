---
name: kriging-orchestrator
description: Orchestrate a first-pass kriging workflow using existing Evo objects and the evo-mcp compute tools. Use this whenever the user wants to run kriging from existing pointsets, variograms, block models, or regular grids using primitive IDs and attribute names.
---

# Kriging Orchestrator

Use this skill to run one or more kriging tasks through MCP while keeping `KrigingParameters` as the canonical model.

Internally, use a two-step process:

1. Build a validated payload from primitive inputs plus `workspace_id`.
2. Run kriging using a `scenarios` list and a separate `workspace_id`.

`workspace_id` is required when building parameters so the tool can resolve object IDs, but it is not embedded in the returned `KrigingParameters` payload.

## Trigger Conditions

Use this skill when the user wants to:

- run kriging from existing Evo objects
- build kriging inputs from object IDs and attribute names
- execute kriging through the `kriging_build_parameters` and `kriging_run` MCP tools
- avoid inventing a second request model

## Workflow

1. Use the `object-discovery` skill if source, variogram, or target objects are not already resolved.
2. Confirm `workspace_id`, target object and target attribute, source pointset object and source attribute, and variogram.
3. Confirm primitive inputs: target object UUID + target attribute name, source pointset UUID + source attribute name, and variogram UUID.
4. Call `kriging_build_parameters` with primitive IDs and typed search/method inputs.
5. Pass the returned payload as a single-item `scenarios` list to `kriging_run(workspace_id=..., scenarios=[...])`.

```python
payload = kriging_build_parameters(
    workspace_id=workspace_id,
    target_object_id=target_object_id,
    target_attribute=target_attribute,
    point_set_object_id=point_set_object_id,
    point_set_attribute=point_set_attribute,
    variogram_object_id=variogram_object_id,
    search=search,
    method={"type": "ordinary"},
)

kriging_run(workspace_id=workspace_id, scenarios=[payload])
```

If the tool returns a wrapped result (for example `{ "payload": {...} }`), pass the inner payload object:

```python
build_result = kriging_build_parameters(...)
kriging_run(workspace_id=workspace_id, scenarios=[build_result["payload"]])
```

## Rules

- Pass `workspace_id` to `kriging_build_parameters` so the tool can resolve source, target, and variogram objects.
- Keep `workspace_id` separate from the returned `KrigingParameters` payload and from the `scenarios` entries passed to `kriging_run`.
- `kriging_run` accepts only `scenarios: list[KrigingParameters]`; do not pass a single payload directly.
- Ensure `scenarios` is non-empty before calling `kriging_run`.
- Prefer primitive UUID inputs for objects and attribute names for source/target fields.
- Do not pass a JSON string when a structured object will do.
- Always use `kriging_build_parameters` before `kriging_run`.
- Let `kriging_build_parameters` return the canonical run payload shape. It performs internal search payload normalization (including `ellipsoid_ranges` to `ranges`) for MCP round-trips.
- Use strict canonical inputs and fix invalid IDs/attributes instead of guessing alternate shapes.
- Let the tool derive canonical references from typed objects; do not hand-build Evo reference URLs or raw JMESPath expressions.
- Follow role constraints enforced by the tool typing:
    - `target_object_id`: UUID referencing a `BlockModel` or `Regular3DGrid`
    - `point_set_object_id`: UUID referencing a `PointSet`
    - `variogram_object_id`: UUID referencing a `variogram`

## Required Inputs

- `workspace_id`
- `target_object_id` and `target_attribute`
- `point_set_object_id` and `point_set_attribute`
- `variogram_object_id`
- search neighborhood

## First-Pass Scope

- Single run and multi-scenario runs are both supported.
- Existing objects only.
- Targets may be block models or regular grids.
- No server-side visualization helpers.

## Example Pattern

```python
payload = kriging_build_parameters(
    workspace_id=workspace_id,
    target_object_id="<block-model-or-grid-uuid>",
    target_attribute="kriged_grade",
    point_set_object_id="<pointset-uuid>",
    point_set_attribute="grade",
    variogram_object_id="<variogram-uuid>",
    search={
        "ellipsoid": {
            "ranges": {"major": 200.0, "semi_major": 150.0, "minor": 100.0}
        },
        "max_samples": 20,
    },
    method={"type": "ordinary"},
)

kriging_run(workspace_id=workspace_id, scenarios=[payload])
```

## Validation Notes

- If `kriging_build_parameters` fails, fix those input errors first and rebuild before running.
- If `kriging_build_parameters` fails because `workspace_id` is missing, provide it and rebuild. The build step requires workspace context even though the returned payload does not include it.
- If `kriging_run` fails due to missing source attribute, re-check that `point_set_attribute` exactly matches an attribute name on the source pointset.
- If `kriging_run` fails validation on object references, re-check workspace/object role pairing and retry.
- Do not patch malformed references or fabricate attribute expressions at run time. Fix upstream inputs, rebuild payload, and rerun.

## Multi-Scenario Pattern

Use this for parameter sweeps:

```python
scenarios = [
    kriging_build_parameters(
        workspace_id=workspace_id,
        target_object_id=target_object_id,
        target_attribute=f"kriged_grade_ms_{max_samples}",
        point_set_object_id=point_set_object_id,
        point_set_attribute=point_set_attribute,
        variogram_object_id=variogram_object_id,
        search={
            "ellipsoid": {
                "ranges": {"major": 200.0, "semi_major": 150.0, "minor": 100.0}
            },
            "max_samples": max_samples,
        },
        method={"type": "ordinary"},
    )
    for max_samples in [8, 12, 20]
]

kriging_run(workspace_id=workspace_id, scenarios=scenarios)
```