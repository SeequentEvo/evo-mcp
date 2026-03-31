# Block Model Payload Examples

Use this reference when generating or validating local `block_model_data` payloads.

## Canonical Local Payload

```json
{
  "name": "Grade Block Model",
  "description": "Optional description",
  "coordinate_reference_system": "EPSG:32632",
  "size_unit_id": "m",
  "origin": {
    "x": 1000.0,
    "y": 2000.0,
    "z": 300.0
  },
  "n_blocks": {
    "nx": 80,
    "ny": 60,
    "nz": 20
  },
  "block_size": {
    "dx": 25.0,
    "dy": 25.0,
    "dz": 10.0
  }
}
```

## Wrapped Payload (Accepted by regular_block_model_publish)

```json
{
  "block_model_data": {
    "name": "Grade Block Model",
    "origin": {"x": 1000.0, "y": 2000.0, "z": 300.0},
    "n_blocks": {"nx": 80, "ny": 60, "nz": 20},
    "block_size": {"dx": 25.0, "dy": 25.0, "dz": 10.0}
  }
}
```

## Minimal Valid Payload

```json
{
  "name": "Minimal BM",
  "origin": {"x": 0.0, "y": 0.0, "z": 0.0},
  "n_blocks": {"nx": 10, "ny": 10, "nz": 5},
  "block_size": {"dx": 5.0, "dy": 5.0, "dz": 2.0}
}
```

## Common Validation Failures

- Missing nested objects: `origin`, `n_blocks`, `block_size`
- Non-positive values in `block_size`
- Non-integer values in `n_blocks`
- Missing or empty `name`
