---
name: evo-object-visualisation
description: Use this skill when the user wants to view Evo objects in the Viewer or generate portal links — even if they just say "show me" or "open in Evo." Requires explicit object IDs. Note — variograms are not currently supported.
---

# Object Visualisation

Use this skill to build a combined viewer link from user-supplied Evo object IDs.

## Verification and Limitations

This skill requires the evo-mcp server and its associated tools to function; without them, it is not usable. This skill is assistive and may produce incomplete, incorrect, or variable results over time.

For details, call `get_skills_disclosure` tool or consult the repository disclaimers.

## Trigger Conditions

Use this skill when the user wants to:

- view one or more Evo objects together
- generate viewer links from explicit object IDs
- generate portal links for each object in the same response

Do not use this skill when:

- object IDs are not yet known and discovery is required first
- the user wants variogram visualisation (currently unsupported)
- the request is not limited to generating viewer or portal links from known object IDs

## Tools

| Tool | Use |
|---|---|
| `viewer_generate_multi_object_links` | Generate a combined viewer URL and per-object portal links for a list of object IDs |

## Workflow

1. Confirm the `workspace_id`.
2. Confirm the explicit object ID list.
3. Call `viewer_generate_multi_object_links`.
4. Return the combined viewer URL and per-object portal URLs.

## Rules

- This skill is generic and not workflow-specific.
- Require explicit user-supplied object IDs.
- Do not infer or discover objects unless the user asks for that separately.

## Gotchas

- Variograms are not supported by `viewer_generate_multi_object_links`; fail clearly and suggest alternatives.
- A valid workspace ID with invalid object IDs still fails link generation; report exactly which IDs failed resolution.
- This skill is link-only; do not mutate objects or start discovery unless explicitly requested.

## Required Inputs

- `workspace_id`
- `object_ids`

## Error Handling

- Empty object ID list: fail with a message indicating at least one object ID is required.
- Invalid object ID: fail with a resolution error identifying which ID could not be found.
- Workspace not accessible: fail with an explicit workspace resolution message.
- Variogram request: fail with a clear "currently unsupported" message.

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `references/error_patterns.md` when link generation fails and you need standard resolution guidance by error type.