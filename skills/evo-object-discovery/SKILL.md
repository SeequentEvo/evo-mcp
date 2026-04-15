---
name: evo-object-discovery
description: Use this skill when the user needs to find, browse, or identify objects in an Evo workspace — even if they just say "what data do I have?" or "find my copper samples." Resolves object candidates before downstream workflows.
---

# Object Discovery

Use this skill to locate existing Evo objects with MCP tools before any domain-specific workflow.

## Trigger Conditions

Use this skill when the user needs to:

- find existing objects in a workspace
- narrow candidates by schema type, name, or path hints
- select objects for downstream kriging, validation, or management workflows
- identify which objects are available before running estimation

Do not use this skill when:

- the user already has resolved object IDs
- the request is about creating or modifying objects rather than locating existing workspace objects
- the request is about changing object state or persistence rather than discovery

## Tools

| Tool | Use |
|---|---|
| `list_objects` | List all objects in a workspace, optionally filtered by schema type |
| `get_object` | Fetch metadata for a specific object by ID or path |

## Workflow

1. Confirm the `workspace_id`.
2. Identify the object types needed.
3. Call `list_objects(workspace_id=...)`.
4. Filter results by schema and user-provided hints.
5. If needed, call `get_object(...)` on the strongest matches.
6. Return a concise shortlist grouped by intended role.

## Output Shape

Return results grouped by role with enough detail for follow-up tool calls:

- `workspace_id`
- `requested_types`
- `candidates`
- `ambiguities`

Each candidate should include:

- `name`
- `path`
- `schema_id`

Internal identifiers (`id`, `version_id`) are carried in the result for downstream tool use but should not be surfaced to the user in conversation.

## Rules

- Prefer existing MCP tools over inventing server-side search behavior.
- Be explicit when multiple matches remain.
- Do not guess the final object if the workspace contains plausible alternatives.
- Return discoveries in a form that can feed directly into downstream tool calls.
- Infer role/type compatibility from `schema_id`.
- Prefer the newest relevant candidate when multiple objects share name/path hints, using recency metadata.

## Gotchas

- Similar names across schemas are common; never assume the intended object without confirming type/role fit.
- Path/name matches alone can be stale; prefer the newest relevant candidate when duplicates exist.
- Internal IDs are for downstream tool chaining and should not be surfaced unless needed to unblock.

## Example

If the user asks for a point set named like `Ag_LMS1`, list objects in the workspace, keep only pointset-like schemas, then return the best matches by name, path, and schema type. Present them to the user by name for confirmation.

## Required Inputs

- `workspace_id`

## Optional Inputs

- Schema type filter (e.g., `pointset`, `variogram`, `block-model`)
- Name or path hints for narrowing candidates

## Error Handling

- Empty workspace: report that no objects were found and suggest checking the workspace ID.
- No matches for filter: report the filter criteria and the types available.
- Ambiguous matches: present all plausible candidates and ask the user to choose.

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `references/output_shape.md` when you need the exact candidate output contract for downstream tool chaining.