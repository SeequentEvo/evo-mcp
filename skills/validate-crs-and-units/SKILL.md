---
name: validate-crs-and-units
description: Validates coordinate reference system compatibility between geoscience objects.
---

# Validate CRS And Units

Use this skill after the source and target are resolved and before search-neighborhood design.

## Trigger Conditions

Use this skill when the user needs to:

- compare source and target CRS before spatial estimation
- verify coordinate reference system compatibility between objects
- gate a workflow on spatial compatibility checks

## Workflow

1. Confirm `source_name` and `target_name` are registered in the session.
2. Call `spatial_validate_crs_and_units` with the object names.
3. Inspect the returned `status`.
4. Route the workflow according to the status.

## Rules

- If status is `compatible`, continue.
- If status is `unknown`, require explicit confirmation before execution.
- If status is `mismatch`, stop the workflow until resolved.
- Do not derive or change neighborhood ranges inside this skill.
- This tool operates on the local staging layer — no Evo API calls.

## Required Inputs

- `source_name` — name of the source object in the session registry
- `target_name` — name of the target object in the session registry

## Output Shape

Return the validation result and the workflow action:

- `status`
- `message`
- `source`
- `target`
- `next_action`

Where `next_action` is one of:

- `continue`
- `confirm`
- `stop`

## Error Handling

- Object not found in session: report that the object name could not be resolved and suggest checking staging.
- CRS not defined on an object: return `unknown` status and require user confirmation before proceeding.
- Both objects missing CRS: return `unknown` status and warn that spatial compatibility cannot be verified.