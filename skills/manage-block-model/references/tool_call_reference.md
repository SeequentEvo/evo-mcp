# Tool Call Reference

Use this reference for direct block model workflows.

## Design from explicit extents

```python
staging_create_object(
    object_type="regular_block_model",
    params={
        "object_name": "Domain BM",
        "object_path": "/blockmodels/domain_bm.json",
        "block_size_x": 25,
        "block_size_y": 25,
        "block_size_z": 10,
        "x_min": 1000,
        "x_max": 3000,
        "y_min": 2000,
        "y_max": 3500,
        "z_min": 100,
        "z_max": 600,
    },
)

staging_invoke_interaction(
    object_name="Domain BM",
    interaction_name="get_definition_details",
)
```

## Design then publish

```python
staging_create_object(object_type="regular_block_model", params={...})
staging_publish_object(...)
```
