---
name: evo-kriging-run
description: Executes kriging estimation scenarios from fully resolved inputs — source, target, variogram, and search neighborhood must all be ready.
---

# Kriging Run

Use this skill after source, target, variogram, CRS, and neighborhood inputs are all resolved. This skill builds validated `KrigingParameters` scenarios and executes them through `kriging_run`, returning structured results with inspection links.

## Trigger Conditions

Use this skill when:

- all kriging object IDs (source, target, variogram) are known
- a canonical `search` neighborhood payload is already available
- CRS validation has passed or been explicitly accepted
- the user wants to build and execute kriging estimation

Do not use this skill when:

- object IDs have not been resolved yet
- the neighborhood has not been defined yet
- CRS has not been validated (use `validate-crs-and-units` first)
- the user only wants to inspect or design inputs without running

## Tools

This skill uses two compute tools:

| Tool | Purpose |
| --- | --- |
| `kriging_build_parameters` | Build a validated `KrigingParameters` payload from primitive inputs |
| `kriging_run` | Execute one or more scenarios in parallel |

## Workflow

### Single Scenario

1. Call `kriging_build_parameters` with all required inputs.
2. Collect the returned payload into a single-element `scenarios` list.
3. Call `kriging_run(workspace_id, scenarios)`.
4. Summarize results: target name, attribute operation, attribute name, and inspection links.

### Scenario Variations

When the user wants to compare different kriging configurations, build each variation as a separate scenario and run them together.

Common variation patterns:

- **Multiple target attributes**: Same source/variogram/neighborhood, different `target_attribute` per scenario.
- **Multiple target domains**: Same source/variogram/neighborhood, different `target_region_filter` per scenario.
- **Method comparison**: Same inputs, one scenario with ordinary kriging, another with simple kriging using `{"type": "simple", "mean": ...}`.
- **Neighborhood sensitivity**: Same inputs, different `search` neighborhood configurations such as moderate versus broad search extents.

For each variation:

1. Call `kriging_build_parameters` once per configuration.
2. Collect all returned payloads into the `scenarios` list.
3. Call `kriging_run(workspace_id, scenarios)` once with all scenarios.
4. Results are returned in the same order as input scenarios.

## Tool Call Reference

### Building a Scenario

```
kriging_build_parameters(
	workspace_id=workspace_id,
	target_object_id=target_object_id,
	target_attribute=target_attribute,
	point_set_object_id=point_set_object_id,
	point_set_attribute=point_set_attribute,
	variogram_object_id=variogram_object_id,
	search=neighborhood,
	method={"type": "ordinary"},
	target_region_filter=None,
	block_discretisation=None,
)
```

### Running Scenarios

```
kriging_run(
	workspace_id=workspace_id,
	scenarios=[payload_1, payload_2, ...]
)
```

`scenarios` must be a non-empty list. Each entry is a payload returned by `kriging_build_parameters`.

## Rules

- Always use `kriging_build_parameters` to build payloads. Do not hand-construct `KrigingParameters` JSON.
- Pass `workspace_id` to both `kriging_build_parameters` and `kriging_run` separately. It is not embedded in the scenario payload.
- `kriging_run` accepts `scenarios` as a list. Do not pass a single payload directly.
- Build one scenario per `kriging_build_parameters` call and collect them into the list before calling `kriging_run`.
- Do not add a separate preflight step just to determine whether a target attribute will be created or updated; report the resolved operation from `kriging_run` results.
- Use canonical field names: `search` for the search neighborhood, `method` for the kriging method.
- The tool automatically normalizes search neighborhood field names (e.g., `ellipsoid_ranges` → `ranges`) for SDK compatibility. No manual field renaming is needed when passing results between skills.
- Results from `kriging_run` are ordered to match the input `scenarios` list.
- Do not rewrite or reshape payloads returned by `kriging_build_parameters` before passing to `kriging_run`.

## Required Inputs

All object identifiers below are resolved upstream — users work with names, not UUIDs.

- `workspace_id`
- `target_object_id`: resolved identifier of the target block model or regular grid
- `target_attribute`: attribute name to create or update on the target
- `point_set_object_id`: resolved identifier of the source point set
- `point_set_attribute`: existing source attribute name on the point set
- `variogram_object_id`: resolved identifier of the variogram
- `search`: a canonical search neighborhood payload

## Optional Inputs

- `method`: defaults to ordinary kriging. Use `{"type": "simple", "mean": <value>}` for simple kriging.
- `target_region_filter`: optional region filter for the target object.
- `block_discretisation`: optional sub-block discretisation settings.

## Output Shape

`kriging_run` returns:

```
{
	"status": "success",
	"scenarios_completed": <int>,
	"results": [
		{
			"status": "success",
			"message": "...",
			"target": {
				"name": "...",
				"reference": "...",
				"schema_id": "...",
				"locator": { "org_id", "workspace_id", "object_id", "hub_url" },
				"attribute": { "operation": "create"|"update", "name": "...", "requested": "..." }
			},
			"presentation": {
				"html": "...",
				"portal_url": "...",
				"viewer_url": "..."
			}
		}
	]
}
```

## Result Summarization

After `kriging_run` completes, summarize each result:

1. State the target object name and attribute operation (created or updated).
2. Provide the portal and viewer inspection links.
3. If multiple scenarios ran, number them in order.

## Error Handling

- If `kriging_build_parameters` fails because of an unresolvable UUID, missing attribute, or role mismatch, report the error and do not proceed to `kriging_run`.
- If `kriging_run` fails for any scenario, report which scenario or scenarios failed.
- If CRS mismatch warnings were already acknowledged during setup, surface them again in the response rather than silently ignoring them.

## Performance Troubleshooting

If kriging takes too long or times out:
- **Reduce block count**: Use larger block sizes to decrease the number of blocks to estimate.
- **Reduce `max_samples`**: Fewer samples per block means faster estimation. Try 12–16 instead of 20+.
- **Reduce search ellipsoid ranges**: A smaller search radius means fewer candidate samples per block. Try 1.5× the variogram range instead of 3×.
- **Reduce scenario count**: Run fewer scenarios per batch.

If kriging produces many unestimated blocks:
- **Increase search ranges**: The ellipsoid may be too small to find enough samples. Try 2–3× the variogram range.
- **Decrease `min_samples`**: Lowering the minimum sample requirement allows estimation in sparse areas.
- **Check data coverage**: Verify your source data covers the target block model extents.