---
name: evo-object-discovery
description: Discover existing Evo geoscience objects for downstream workflows. Use this whenever the user needs to find existing objects by workspace, schema type, name hint, or path hint.
---

# Object Discovery

Use this skill to locate existing Evo objects with MCP tools before any domain-specific workflow.

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

## Object Type Reference

| Schema type | Typical role |
|---|---|
| `pointset` | Sample source data |
| `variogram` | Spatial continuity model |
| `block-model` / `regular-3d-grid` | Estimation or analysis target |

## Preferred Output

Return results grouped by role with enough detail for follow-up tool calls:

- `workspace_id`
- `requested_types`
- `candidates`
- `ambiguities`

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
- Return discoveries in a form that can feed directly into downstream tool calls.
- Infer role/type compatibility from `schema_id`.
- Prefer the newest relevant candidate when multiple objects share name/path hints, using `version_id` and recency metadata.

## Example

If the user asks for a point set named like `Ag_LMS1`, list objects in the workspace, keep only pointset-like schemas, then return the best matches with IDs, names, paths, schema IDs, and version IDs.