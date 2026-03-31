---
name: evo-kriging-run
description: Build and execute kriging scenarios from resolved inputs using the kriging_build_parameters and kriging_run compute tools. Use this skill whenever the user already has workspace, source, target, variogram, and neighborhood inputs ready and wants to run one or more kriging estimation scenarios, including method comparisons, attribute variations, or neighborhood sensitivity checks.
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

- object IDs have not been resolved yet (use `evo-object-discovery` first)
- the neighborhood has not been defined yet
- CRS has not been validated (use `validate-crs-and-units` first)
- the user only wants to inspect or design inputs without running

## Tools

This skill uses two compute tools:

| Tool | Purpose |
| --- | --- |
| `kriging_build_parameters` | Build a validated `KrigingParameters` payload from primitive inputs |
| `kriging_run` | Execute one or more scenarios in parallel |

Use `viewer_generate_multi_object_links` only if the user wants a combined viewer across multiple kriging targets.

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
- The tool internally normalizes `ellipsoid_ranges` → `ranges` for round-trip compatibility. Use `ranges` in neighborhood inputs (matching the SDK constructor), e.g. `"ranges": {"major": ..., "semi_major": ..., "minor": ...}`.
- Results from `kriging_run` are ordered to match the input `scenarios` list.
- Do not rewrite or reshape payloads returned by `kriging_build_parameters` before passing to `kriging_run`.

## Required Inputs

- `workspace_id`
- `target_object_id`: UUID of the target BlockModel or Regular3DGrid
- `target_attribute`: attribute name to create or update on the target
- `point_set_object_id`: UUID of the source PointSet
- `point_set_attribute`: existing source attribute name on the PointSet
- `variogram_object_id`: UUID of the variogram object
- `search`: a canonical search neighborhood payload that is already defined before this skill runs

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
4. If the user wants a combined viewer for multiple targets, use `viewer_generate_multi_object_links`.

## Error Handling

- If `kriging_build_parameters` fails because of an unresolvable UUID, missing attribute, or role mismatch, report the error and do not proceed to `kriging_run`.
- If `kriging_run` fails for any scenario, report which scenario or scenarios failed.
- If CRS mismatch warnings were already acknowledged during setup, surface them again in the response rather than silently ignoring them.