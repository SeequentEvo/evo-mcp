---
name: object-discovery
description: Discover existing Evo geoscience objects for downstream workflows. Use this whenever the user needs to find existing objects by workspace, schema type, name hint, or path hint.
---

# Object Discovery

Use this skill to locate existing Evo objects with MCP tools before any domain-specific orchestration.

## Goals

- Find candidate objects in a workspace.
- Narrow candidates by schema type and name or path hints.
- Return clear, reusable object selections for downstream workflows.
- Prefer candidates with explicit `version_id` for deterministic follow-up runs.

## Workflow

1. Confirm the `workspace_id`.
2. Identify the object types needed.
3. Call `list_objects(workspace_id=...)`.
4. Filter results by schema and user-provided hints.
5. If needed, call `get_object(...)` on the strongest matches.
6. Return a concise shortlist grouped by intended role.

Role mapping for kriging:

- source: `pointset`
- variogram: `variogram`
- target: `block-model` or `regular-3d-grid`

## Preferred Output

Return results grouped by role with enough detail for follow-up tool calls:

- `workspace_id`
- `requested_types`
- `candidates`
- `ambiguities`

For kriging workflows, also include a lightweight `kriging_parameters_seed` map:

- `target_object_id`
- `point_set_object_id`
- `variogram_object_id`
- `target_attribute` (if known)
- `point_set_attribute` (if known)

If attribute names are unknown, include `attribute_follow_up_required: true` and ask for the exact source attribute name before execution.

Each candidate should include:

- `id`
- `name`
- `path`
- `schema_id`
- `version_id`

## Rules

- Prefer existing MCP tools over inventing server-side search behavior.
- Be explicit when multiple matches remain.
- Do not guess the final object if the workspace contains plausible alternatives.
- Look for pointsets, variograms, block models, and regular grids.
- Return discoveries in a form that can feed directly into downstream tool calls.
- Infer role/type compatibility from `schema_id`.
- Prefer the newest relevant candidate when multiple objects share name/path hints, using `version_id` and recency metadata.
- Prefer role names that align with `KrigingToolParameters` fields.

## Example

If the user asks for a pointset named like `Ag_LMS1`, list objects in the workspace, keep only pointset-like schemas, then return the best matches with IDs, names, paths, schema IDs, and version IDs.