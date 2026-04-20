# Tool Call Reference

Use this reference for direct search neighborhood creation.

## Create from variogram name

```python
staging_create_object(
    object_type="search_neighborhood",
    params={
        "max_samples": 20,
        "min_samples": 4,
        "variogram_name": "CU variogram",
        "scale_factor": 2.0,
        "preset": "moderate",
        "selection_mode": "first",
    },
)
```

## Create from explicit ranges

```python
staging_create_object(
    object_type="search_neighborhood",
    params={
        "max_samples": 20,
        "major": 200.0,
        "semi_major": 150.0,
        "minor": 100.0,
        "dip_azimuth": 0.0,
        "dip": 0.0,
        "pitch": 0.0,
    },
)
```

## Create from published variogram object

```python
staging_create_object(
    object_type="search_neighborhood",
    params={
        "workspace_id": workspace_id,
        "variogram_object_id": variogram_object_id,
        "max_samples": 20,
        "scale_factor": 2.0,
    },
)
```
