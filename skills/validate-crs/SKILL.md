---
name: validate-crs
description: Use this skill when source and target objects need to be checked for spatial compatibility before running estimation — even if the user says "make sure everything aligns" or doesn't mention CRS directly.
---

# Validate CRS

Use this skill to verify spatial compatibility between two staged objects before running estimation. Operates entirely on the local staging layer — no Evo API calls.

## Verification and Limitations

This skill requires the evo-mcp server and its associated tools to function; without them, it is not usable. This skill is assistive and may produce incomplete, incorrect, or variable results over time.

For details, call `get_skills_disclosure` tool or consult the repository disclaimers.

## Trigger Conditions

Use this skill when the user needs to:

- compare source and target CRS before spatial estimation
- verify coordinate reference system compatibility between objects
- gate a workflow on spatial compatibility checks

Do not use this skill when:

- the request is not limited to checking spatial compatibility between two staged objects
- the required source and target objects are not yet available in the current session
- the user needs actions beyond determining compatibility status and the next workflow gate

## Tools

| Tool | Use |
|---|---|
| `staging_spatial_validation` | Compare CRS of two staged objects and return compatibility status |

## Workflow

1. Confirm `source_name` and `target_name` are registered in the session.
2. Call `staging_spatial_validation` with the object names.
3. Inspect the returned `status`.
4. Route the workflow according to the status.

## Rules

- If status is `compatible`, continue.
- If status is `unknown`, require explicit confirmation before execution.
- If status is `mismatch`, stop the workflow until resolved.
- Do not derive or change neighborhood ranges inside this skill.
- This tool operates on the local staging layer — no Evo API calls.

## Gotchas

- `unknown` is not a pass state; it requires explicit user confirmation before continuing.
- Matching object names do not imply matching CRS; always run validation before estimation.
- CRS checks only cover staged objects in-session. Imported/published state outside the session is irrelevant until staged.

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

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `references/payload_contract.md` when you need exact output field names and `next_action` semantics.