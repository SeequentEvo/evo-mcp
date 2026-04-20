# Tool Call Reference

Use this reference for direct variogram workflows.

## Create a variogram

```python
staging_create_object(
    object_type="variogram",
    params={
        "object_name": "CU variogram",
        "sill": 1.0,
        "nugget": 0.1,
        "structures": [...],
    },
)
```

## Inspect structure details

```python
staging_invoke_interaction(
    object_name="CU variogram",
    interaction_name="get_structure_details",
    params={"selection_mode": "largest_major"},
)
```

## Derive search parameters

```python
staging_invoke_interaction(
    object_name="CU variogram",
    interaction_name="get_search_parameters",
    params={"scale_factor": 2.0, "selection_mode": "first"},
)
```
