# Results and Errors

Use this reference for concise run reporting and failure handling.

Use the documented call sequence directly.

## Tool Call Reference

### Build one scenario

```python
kriging_build_parameters(
	workspace_id=workspace_id,
	params={
		"target_object_id": target_object_id,
		"target_attribute": target_attribute,
		"point_set_object_id": point_set_object_id,
		"point_set_attribute": point_set_attribute,
		"variogram_object_id": variogram_object_id,
		"search": neighborhood,
		"method": {"type": "ordinary"},
	},
)
```

### Run one or more scenarios

```python
kriging_run(
	workspace_id=workspace_id,
	scenarios=[payload_1, payload_2],
)
```

## Execution Notes

- Build each scenario first, then execute scenarios as one batch.
- Keep scenario ordering intentional, because results map back by input order.
- Pass build outputs directly into execution without reshaping.

## Reporting Checklist

For each scenario result, report:

1. scenario index/order
2. target object name
3. attribute operation (`create` or `update`)
4. portal and viewer links

## Error Handling Checklist

- If parameter build fails, do not run execution.
- Report the blocking problem clearly and identify the affected scenario.
- If a scenario run fails, include the failing scenario and message.
- Preserve and report successful scenario results in mixed-success batches.
- If CRS warnings were accepted upstream, repeat that context in final run reporting.
