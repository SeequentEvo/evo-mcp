---
name: evo-kriging-execute
description: Use this skill to execute kriging when source, target, and variogram are already published Evo objects and all IDs are resolved. Search neighborhood and run properties are supplied manually — do not use this skill for setup or object discovery.
---

# Kriging Execute

Use this skill only for execution.

Only source, target, and variogram must be resolved to published Evo objects. Search neighborhood and other run properties are provided manually as execution inputs.

This skill builds validated scenarios with `kriging_build_parameters`, then executes them with `kriging_run`.

## Trigger Conditions

Use this skill when:

- source, target, and variogram are already published Evo objects
- all required IDs and attributes are already resolved
- search neighborhood payload is provided as manual run input
- any method/region filter/discretisation settings are provided as manual run inputs
- CRS validation has already passed (or has been explicitly accepted)
- the user wants to run kriging now

Do not use this skill when:

- object IDs, references, or attribute names are still unknown
- source/target/variogram objects are not published to Evo yet
- CRS has not been validated yet
- the user is still resolving setup details rather than executing ready inputs

## Tools

Use only these tools:

| Tool | Use |
| --- | --- |
| `kriging_build_parameters` | Build one validated scenario payload from resolved primitive inputs |
| `kriging_run` | Execute one or more scenarios in one batch |

Use the documented tool path directly. Assume tool contracts are stable for this workflow.

## Workflow

1. Confirm execution readiness:
   - objects are already published in Evo
   - object IDs and attribute names are already resolved
   - neighborhood and run settings are explicitly provided as inputs
   - CRS status is already resolved
2. Build each scenario with `kriging_build_parameters`.
3. Collect returned payloads into a non-empty `scenarios` list.
4. Call `kriging_run(workspace_id, scenarios)` once per batch.
5. Summarize each result with target, attribute operation, and inspection links.

## Rules

- Always use `kriging_build_parameters` to build payloads. Do not hand-construct `KrigingParameters` JSON.
- This skill does not publish objects and does not resolve names to IDs.
- Source, target, and variogram must already exist as published Evo objects before execution.
- Search neighborhood, method, region filter, and block discretisation are manual run inputs (not published Evo objects).
- Pass scenario fields under `params`; pass `workspace_id` separately to both tools.
- Build one scenario per call, then batch them in `scenarios` for `kriging_run`.
- Pass payloads through unchanged from `kriging_build_parameters` to `kriging_run`.
- Report attribute create/update from `kriging_run` results; do not preflight this separately.
- Results are ordered to match scenario input order.
- Only use additional discovery if a tool call fails and you need to troubleshoot inputs or fields.

## Result Summarization

After `kriging_run`, summarize each scenario in order:

1. target object name
2. attribute outcome (created or updated)
3. portal/viewer links

## Gotchas

- Pass `workspace_id` separately to BOTH `kriging_build_parameters` AND `kriging_run` — omitting it from either call will fail.
- Do not pass the search neighborhood as an Evo object ID. It is always a manual payload, even when derived from a staged variogram.
- Results are ordered to match scenario input order. A failing scenario does not cancel others — preserve successful results.
- Do not hand-construct `KrigingParameters` JSON. Always use `kriging_build_parameters` to produce the payload.

## Error Handling

- If parameter build fails, stop and report the exact blocking field(s).
- If run fails, report the failing scenario(s) and preserve successful results for others.
- If CRS warnings were previously accepted, surface them again in the run summary.

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `references/results_and_errors.md` if `kriging_run` returns an error, unexpected status, or a scenario fails.
- Read `references/scenario_patterns.md` if the user wants to run multiple scenarios with varying configurations (methods, neighborhoods, attributes).
- Read `references/performance_troubleshooting.md` if the user asks why kriging is slow or wants to optimize run performance.