---
name: manage-variogram
description: Use this skill when the user needs to define a variogram model from parameters, inspect its structure or geometry, plot semivariance curves, or derive search ranges — even if they just say "set up my variogram" or provide range values directly.
---

# Variogram Management

Use this skill for local variogram handling: create payloads from canonical structure lists, inspect structure and ellipsoid details, inspect principal-direction curve details, and derive search-parameter ranges. All operations are local — no Evo API calls.

## Trigger Conditions

Use this skill when the user needs to:

- create a new variogram payload from modeling parameters
- inspect structure-level variogram details
- inspect ellipsoid geometry details and optional plotting points
- inspect principal-direction semivariance curves
- derive search ellipsoid parameters from selected variogram structures

Do not use this skill when:

- the request is about persistence to or retrieval from Evo rather than local variogram handling
- the variogram already exists in Evo and needs no local modification

## Tools

All variogram operations use two generic staging tools:

- `staging_create_object(object_type="variogram", params={...})` — build a new variogram from canonical modeling parameters.
- `staging_invoke_interaction(object_name="...", interaction_name="...", params={...})` — call any interaction on a staged variogram.

Use the interactions documented in this skill directly. Assume they work. Only call `staging_list_interactions(object_type="variogram")` if an invocation fails due to an unknown interaction.

### Available Interactions

| `interaction_name` | Purpose |
|---|---|
| `get_summary` | Return sill, nugget, structure count summary. |
| `get_structure_details` | Inspect ranges, rotation, and contribution for a selected structure. |
| `get_ellipsoid_details` | Return ellipsoid geometry with optional 3D surface/wireframe points. |
| `get_curve_details` | Return 2D semivariance curves for principal directions and optional arbitrary direction. |
| `get_search_parameters` | Extract and scale search ellipsoid parameters from a selected structure. |

## Decision Flow

```text
User needs variogram help
|
+-- Needs a new variogram? --> staging_create_object(object_type="variogram", ...)
|
+-- Needs structure details? --> staging_invoke_interaction(..., interaction_name="get_structure_details")
|
+-- Needs ellipsoid details and/or plot points? --> staging_invoke_interaction(..., interaction_name="get_ellipsoid_details")
|
+-- Needs 2D variogram curve details? --> staging_invoke_interaction(..., interaction_name="get_curve_details")
|
+-- Needs scaled search ranges? --> staging_invoke_interaction(..., interaction_name="get_search_parameters")
|
+-- Needs to import or publish? --> outside this skill's scope
```

## Workflow

1. Choose the action path: create, inspect structure, inspect ellipsoid, inspect curves, or derive search parameters.
2. Call `staging_create_object(object_type="variogram", params={...})` for create, otherwise call `staging_invoke_interaction(object_name="...", interaction_name="...", params={...})` for the selected interaction.
3. Keep object references by name throughout the workflow.
4. If visualization is requested, use the corresponding script in `scripts/` and fill it with the returned interaction data.

## Rules

- Keep payloads strict and canonical.
- All tools are local operations — no Evo API calls.
- Use the documented tool path first; do not run discovery calls before execution.
- For multi-structure models, use deterministic selection via `structure_index` or `selection_mode`.
- For `get_search_parameters`, always surface `selected_structure_index` in results.
- Keep user-facing output in object names, not internal identifiers.

## Gotchas

- The total sill must equal `nugget + sum(structure contributions)`. Violating this silently produces a malformed variogram.
- `get_ellipsoid_details` and `get_curve_details` have a `structure_index` param for multi-structure variograms — omitting it defaults to structure 0 and may silently return the wrong structure.
- Variograms cannot be viewed in the Evo Viewer or Portal.

## Visualization Workflows

Variograms and search ellipsoids **cannot** be viewed in the Evo Viewer or Portal. Use the scripts in `scripts/` — read the relevant script, fill in the data section with the tool result, and present the adapted code as a ready-to-run Python snippet.

| User request | Script | Tool calls needed |
|---|---|---|
| 3D ellipsoid (surface or wireframe) | `scripts/plot_ellipsoid_3d.py` | `get_ellipsoid_details` with `include_surface_points`/`include_wireframe_points` |
| Variogram vs. search neighborhood overlay | `scripts/plot_ellipsoid_combined.py` | `get_ellipsoid_details` + `get_search_parameters` |
| 2D semivariance curves | `scripts/plot_variogram_curves_2d.py` | `get_curve_details` (add `azimuth`+`dip` for arbitrary direction) |
| Combined 3D + 2D dashboard | `scripts/plot_dashboard.py` | `get_ellipsoid_details` (wireframe) + `get_curve_details` |

## Error Handling

- `scale_factor <= 0`: provide a positive value.
- variogram has no structures: create or provide a valid variogram first.
- invalid `structure_index`: choose an index in `0..structure_count-1`.
- non-positive selected ranges with point generation requested: choose another structure or correct ranges.
- `n_points < 10` for curve details: increase `n_points`.
- non-positive `max_distance` for curve details: provide a positive value or omit it.
- only one of `azimuth` or `dip` provided: provide both to request arbitrary-direction curves.

## Required Inputs

- For create: `object_name`, `sill`, `nugget`, `structures`.
- For interactions: `object_name`.

## Optional Inputs

- `structure_index`, `selection_mode` for deterministic structure selection.
- `scale_factor` for `get_search_parameters`.
- `n_points`, `max_distance`, `azimuth`, `dip` for `get_curve_details`.
- `include_surface_points`, `include_wireframe_points` for `get_ellipsoid_details`.

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `scripts/plot_ellipsoid_3d.py` when the user wants a 3D ellipsoid (surface or wireframe).
- Read `scripts/plot_ellipsoid_combined.py` when the user wants to compare the variogram ellipsoid with the search neighborhood.
- Read `scripts/plot_variogram_curves_2d.py` when the user wants 2D semivariance curves (principal directions or arbitrary direction).
- Read `scripts/plot_dashboard.py` when the user wants a combined 3D + 2D dashboard view.
- Read `references/tool_call_reference.md` if a tool invocation fails and you need to verify the exact parameter names or call structure.
- Read `references/payload_contract.md` when creating a variogram or when you need exact field names and parameter contracts.
