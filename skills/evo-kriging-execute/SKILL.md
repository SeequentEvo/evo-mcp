---
name: evo-kriging-execute
description: Use this skill to execute kriging when source, target, and variogram are already published Evo objects and all IDs are resolved. Search neighborhood and run properties are supplied manually — do not use this skill for setup or object discovery.
---

# Kriging Execute

Use this skill only for execution.

Only source, target, and variogram must be resolved to published Evo objects. Search neighborhood and other run properties are provided manually as execution inputs.

This skill builds validated scenarios with `kriging_build_parameters`, then executes them with `kriging_run`.

## Verification and Limitations

This skill requires the evo-mcp server and its associated tools to function; without them, it is not usable. This skill is assistive and may produce incomplete, incorrect, or variable results over time.

For details, call `get_skills_disclosure` tool or consult the repository disclaimers.

## Trigger Conditions

Use this skill when:

- source, target, and variogram are already published Evo objects
- all required IDs and attributes are already resolved
- search neighborhood payload is provided as manual run input
- any method/domain filter/discretisation settings are provided as manual run inputs
- the user wants to run kriging now

## Tools

Use only these tools:

| Tool | Use |
| --- | --- |
| `kriging_build_parameters` | Build one validated scenario payload from resolved primitive inputs |
| `kriging_run` | Execute one or more scenarios in one batch |

## Workflow

1. Confirm execution readiness:
   - objects are already published in Evo
   - object IDs and attribute names are already resolved
   - neighborhood and run settings are explicitly provided as inputs
2. Build each scenario with `kriging_build_parameters`.
3. Collect returned payloads into a non-empty `scenarios` list.
4. Call `kriging_run(workspace_id, scenarios)` once per batch.

## Rules

- Always use `kriging_build_parameters` to build payloads — do not hand-construct `KrigingParameters` JSON.
- This skill does not publish objects and does not resolve names to IDs.
- Source, target, and variogram must already exist as published Evo objects before execution.
- Search neighborhood, method, domain filter, and block discretisation are manual run inputs (not published Evo objects).
- Pass scenario fields under `params`; pass `workspace_id` separately to both tools.
- Build one scenario per call, then batch them in `scenarios` for `kriging_run`.
- Pass payloads through unchanged from `kriging_build_parameters` to `kriging_run`.

## Gotchas

- Pass `workspace_id` separately to BOTH `kriging_build_parameters` AND `kriging_run` — omitting it from either call will fail.
- Do not pass the search neighborhood as an Evo object ID. It is always a manual payload, even when derived from a staged variogram.
- A failing scenario does not cancel others — preserve successful results.

## Error Handling

- If parameter build fails, stop and report the exact blocking field(s).
- If a scenario run fails, include the failing scenario and message.
- Preserve and report successful scenario results in mixed-success batches.
- If CRS warnings were accepted upstream, repeat that context in final run reporting.

## Execution Notes

- Build each scenario first, then execute scenarios as one batch.
- Keep scenario ordering intentional, because results map back by input order.
- Pass build outputs directly into execution without reshaping.