# Tool Call Reference

Use this reference for direct point-set workflows.

## Build and inspect a point set

```python
staging_create_object(
    object_type="point_set",
    params={
        "object_name": "Assays",
        "csv_file": "path/to/file.csv",
        "x_column": "Easting",
        "y_column": "Northing",
        "z_column": "RL",
        "coordinate_cleaning": "drop_invalid",
    },
)

staging_invoke_interaction(
    object_name="Assays",
    interaction_name="get_summary",
)

staging_invoke_interaction(
    object_name="Assays",
    interaction_name="get_attribute_details",
)
```

## Build then publish

```python
staging_create_object(object_type="point_set", params={...})
staging_publish_object(...)
```
