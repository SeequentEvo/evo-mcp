# Variogram Payload Contract

Use this reference only when you need exact field names for create payloads or interaction parameters.

## Create Payload

Required fields:
- `object_name`
- `sill`
- `nugget`
- `structures` (one or more structure objects)

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
- Use `variogram_type` (not `type`).
- Ranges are nested under `anisotropy.ellipsoid_ranges` (not top-level).
- Rotation is nested under `anisotropy.rotation`.
- Supported `variogram_type` values: `spherical`, `exponential`, `gaussian`, `cubic`, `linear`, `spheroidal`, `generalisedcauchy`.
- `spheroidal` and `generalisedcauchy` also require `alpha` (one of `3`, `5`, `7`, `9`).

## Interaction Parameters

### `get_search_parameters`
Required:
- `object_name`

Optional:
- `scale_factor` (default `2.0`)
- `structure_index`
- `selection_mode` (`first` or `largest_major`)

### `get_structure_details`
Required:
- `object_name`

Optional:
- `structure_index`
- `selection_mode` (`first` or `largest_major`)

### `get_ellipsoid_details`
Required:
- `object_name`

Optional:
- `structure_index`
- `selection_mode`
- `include_surface_points`
- `include_wireframe_points`

### `get_curve_details`
Required:
- `object_name`

Optional:
- `n_points`
- `max_distance`
- `azimuth`
- `dip`
