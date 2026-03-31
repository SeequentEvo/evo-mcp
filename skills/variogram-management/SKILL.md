---
name: variogram-management
description: Creates, inspects, and plots variogram models locally from parameters — structures, ellipsoids, semivariance curves, and search ranges.
---

# Variogram Management

Use this skill for local variogram handling: create payloads from canonical structure lists, inspect structure and ellipsoid details, inspect principal-direction curve details, and derive search-parameter ranges.

## Trigger Conditions

Use this skill when the user needs to:

- create a new variogram payload from modeling parameters
- inspect structure-level variogram details
- inspect ellipsoid geometry details and optional plotting points
- inspect principal-direction semivariance curves
- derive search ellipsoid parameters from selected variogram structures

## When to Use Each Tool

### Quick Selection Guide

- `variogram_create`: Build a new variogram from canonical modeling parameters.
- `get_variogram_structure_details`: Inspect structure metadata for a selected structure in a multi-structure model.
- `get_variogram_ellipsoid_details`: Return ellipsoid geometry details and optional 3D plotting points.
- `get_variogram_curve_details`: Return 2D semivariance curves for principal directions and optional arbitrary direction.
- `get_variogram_search_params`: Derive scaled search neighborhood ranges from a selected structure.

## Decision Flow

```text
User needs variogram help
|
+-- Needs a new variogram from parameters? --> variogram_create
|
+-- Needs structure details? --> get_variogram_structure_details
|
+-- Needs ellipsoid details and/or plot points? --> get_variogram_ellipsoid_details
|
+-- Needs 2D variogram curve details? --> get_variogram_curve_details
|
+-- Needs scaled search ranges? --> get_variogram_search_params
|
+-- Needs to import or publish? --> outside this skill's scope
```

## Workflow

1. Choose the action path: create, structure-details, ellipsoid-details, curve-details, or derive-search-params.
2. For create: collect modeling inputs and call `variogram_create`.
3. For structure-details: call `get_variogram_structure_details` with `variogram_name`.
4. For ellipsoid-details: call `get_variogram_ellipsoid_details` with `variogram_name`.
5. For curve-details: call `get_variogram_curve_details` with `variogram_name`.
6. For derive-search-params: call `get_variogram_search_params` with `variogram_name`, `scale_factor`, and optional structure selection inputs.
7. Objects are referenced by name throughout the workflow.

## Rules

- Keep payloads strict and canonical.
- `variogram_create` uses a canonical `structures` list.
- The total variogram sill must satisfy `sill = nugget + sum(structure contributions)`.
- Use `get_variogram_structure_details` for deterministic structure selection metadata.
- Use `get_variogram_ellipsoid_details` for ellipsoid geometry details and optional 3D point outputs.
- Use `get_variogram_curve_details` for principal-direction 2D semivariance curve plotting and optional arbitrary-direction curve plotting.
- Keep search-parameter derivation local with `get_variogram_search_params`.
- `get_variogram_search_params` supports deterministic structure selection using `structure_index` or `selection_mode` (`first` or `largest_major`).
- For multi-structure models, always surface `selected_structure_index` in results when deriving search values.
- Objects are referenced by name — users never need to manage internal identifiers.
- All tools are local operations — no Evo API calls.

## Visualization Workflows

Variograms and search ellipsoids **cannot** be viewed in the Evo Viewer or Portal. Use the visualization data returned by `get_variogram_ellipsoid_details` and `get_variogram_curve_details` to generate plotly code for the user.

### 3D Ellipsoid Visualization

When the user asks to see the variogram ellipsoid or search ellipsoid in 3D:

1. Call `get_variogram_ellipsoid_details` with `include_surface_points=True` and/or `include_wireframe_points=True`.
2. Generate plotly code using the returned point arrays.

```python
import plotly.graph_objects as go

# Use surface_points from get_variogram_ellipsoid_details result
fig = go.Figure(data=[
    go.Mesh3d(
        x=result["surface_points"]["x"],
        y=result["surface_points"]["y"],
        z=result["surface_points"]["z"],
        alphahull=0, opacity=0.3, color="blue",
        name="Variogram Ellipsoid"
    )
])
fig.update_layout(
    title="Variogram Ellipsoid",
    scene=dict(aspectmode="data"),
    showlegend=True
)
fig.show()
```

For wireframe style (lighter weight):

```python
fig = go.Figure(data=[
    go.Scatter3d(
        x=result["wireframe_points"]["x"],
        y=result["wireframe_points"]["y"],
        z=result["wireframe_points"]["z"],
        mode="lines", line=dict(color="blue", width=2),
        name="Variogram Ellipsoid"
    )
])
```

To overlay the variogram ellipsoid with a search ellipsoid, call `get_variogram_ellipsoid_details` for the variogram and build a second trace from the search ellipsoid's ranges.

### 2D Variogram Curve Visualization

When the user asks to see variogram curves or the variogram model:

1. Call `get_variogram_curve_details` to get principal-direction curves.
2. Generate plotly code using the returned curve data.

```python
import plotly.graph_objects as go

# Use variogram_curves from get_variogram_curve_details result
curves = result["variogram_curves"]
sill = result["sill"]

fig = go.Figure()
fig.add_trace(go.Scatter(
    x=curves["major"]["distance"], y=curves["major"]["semivariance"],
    mode="lines", name="Major", line=dict(color="red", width=2)
))
fig.add_trace(go.Scatter(
    x=curves["semi_major"]["distance"], y=curves["semi_major"]["semivariance"],
    mode="lines", name="Semi-major", line=dict(color="green", width=2)
))
fig.add_trace(go.Scatter(
    x=curves["minor"]["distance"], y=curves["minor"]["semivariance"],
    mode="lines", name="Minor", line=dict(color="blue", width=2)
))
fig.add_hline(y=sill, line_dash="dash", line_color="gray",
              annotation_text="Sill")

fig.update_layout(
    title="Variogram Model — Principal Directions",
    xaxis_title="Distance",
    yaxis_title="Semivariance",
    showlegend=True
)
fig.show()
```

If an arbitrary-direction curve was requested (via `azimuth` and `dip`), add it as a fourth trace using `result["arbitrary_direction_curve"]`.

### When to Generate Visualization Code

- Generate plotly code when the user asks to "see", "show", "plot", or "visualize" a variogram or ellipsoid.
- Present the code as a ready-to-run Python snippet.
- Always include the sill reference line in 2D curve plots.
- Use `aspectmode="data"` for 3D plots so the ellipsoid shape is not distorted.

## Error Handling

- `scale_factor <= 0`: provide a positive value.
- variogram has no structures: create or provide a valid variogram first.
- invalid `structure_index`: choose an index in `0..structure_count-1`.
- non-positive selected ranges with point generation requested: choose another structure or correct ranges.
- `n_points < 10` for curve details: increase `n_points`.
- non-positive `max_distance` for curve details: provide a positive value or omit it.
- only one of `azimuth` or `dip` provided: provide both to request arbitrary-direction curves.

## Required Inputs

- For create (`variogram_create`):
- `object_name`
- `sill`
- `nugget`
- `structures` containing one or more structure objects

### `structures` array format

Each structure object must use these exact field names:

```json
{
  "variogram_type": "spherical",
  "contribution": 0.9,
  "anisotropy": {
    "ellipsoid_ranges": {
      "major": 200.0,
      "semi_major": 150.0,
      "minor": 100.0
    },
    "rotation": {
      "dip_azimuth": 0.0,
      "dip": 0.0,
      "pitch": 0.0
    }
  }
}
```

Key naming rules:
- Use `variogram_type` (not `type`)
- Ranges are nested under `anisotropy.ellipsoid_ranges` (not top-level)
- Rotation is nested under `anisotropy.rotation`
- Supported `variogram_type` values: `spherical`, `exponential`, `gaussian`, `cubic`, `linear`, `spheroidal`, `generalisedcauchy`
- `spheroidal` and `generalisedcauchy` also require an `alpha` field (one of `3`, `5`, `7`, `9`)
- For search params (`get_variogram_search_params`):
- `variogram_name`
- optional `scale_factor` (default `2.0`)
- optional `structure_index`
- optional `selection_mode` (`first` or `largest_major`)
- For structure details (`get_variogram_structure_details`):
- `variogram_name`
- optional `structure_index`
- optional `selection_mode` (`first` or `largest_major`)
- For ellipsoid details (`get_variogram_ellipsoid_details`):
- `variogram_name`
- optional `structure_index`
- optional `selection_mode` (`first` or `largest_major`)
- optional `include_surface_points`, `include_wireframe_points`
- For curve details (`get_variogram_curve_details`):
- `variogram_name`
- optional `n_points`, `max_distance`, `azimuth`, `dip`
