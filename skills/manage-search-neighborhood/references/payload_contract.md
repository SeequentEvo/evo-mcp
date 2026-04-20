# Search Neighborhood Payload Contract

Use this reference only when exact input/output field names are needed.

## Create Inputs

Required:
- `max_samples`
- One of:
  - explicit `major`, `semi_major`, `minor`
  - `variogram_name` (staged variogram)

Optional:
- `min_samples`
- `dip_azimuth`, `dip`, `pitch`
- `scale_factor`
- `preset` (`tight`=1x, `moderate`=2x, `broad`=3x, `custom`=scale_factor)
- `structure_index`, `selection_mode`

## Output Shape

The neighborhood configuration is returned inside the `result` key of `staging_create_object`:

```json
{
  "object_type": "search_neighborhood",
  "result": {
    "neighborhood": {
      "ellipsoid": {
        "ellipsoid_ranges": { "major": 0.0, "semi_major": 0.0, "minor": 0.0 },
        "rotation": { "dip_azimuth": 0.0, "dip": 0.0, "pitch": 0.0 }
      },
      "max_samples": 20,
      "min_samples": 5
    },
    "derivation": {
      "mode": "user-specified",
      "scale_factor": 2.0,
      "variogram_name": "CU variogram",
      "selected_structure_index": 0,
      "selected_by": "first"
    }
  }
}
```

The neighborhood output can be passed directly to downstream kriging tools; those tools handle any required field normalization.
