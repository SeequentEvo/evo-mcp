# Block Model Payload Contract

Use this reference only when you need exact field names for local regular block model creation.

## Canonical Regular Block Model Payload

```json
{
  "name": "Grade Block Model",
  "description": "Optional description",
  "coordinate_reference_system": "EPSG:32632",
  "size_unit_id": "m",
  "origin": {"x": 1000.0, "y": 2000.0, "z": 300.0},
  "n_blocks": {"nx": 80, "ny": 60, "nz": 20},
  "block_size": {"dx": 25.0, "dy": 25.0, "dz": 10.0}
}
```

## Create Parameters (Extents Path)

Required:
- `params.object_name`
- `params.object_path`
- `params.block_size_x`, `params.block_size_y`, `params.block_size_z`
- `params.x_min`, `params.x_max`, `params.y_min`, `params.y_max`, `params.z_min`, `params.z_max`

Optional:
- `params.description`
- `params.padding_x`, `params.padding_y`, `params.padding_z`
- `params.coordinate_reference_system`
- `params.size_unit_id`
