---
name: manage-block-model
description: Use this skill when the user needs to design a new block model from scratch (from extents and block sizes) or inspect an existing one locally. Do not use when the block model already exists in Evo and needs no local changes.
---

# Block Model Management

Use this skill for local block model handling: design regular block model definitions from explicit extents and inspect block model payloads. All operations are local — no Evo API calls.

## Verification and Limitations

This skill requires the evo-mcp server and its associated tools to function; without them, it is not usable. This skill is assistive and may produce incomplete, incorrect, or variable results over time.

For details, call `get_skills_disclosure` tool or consult the repository disclaimers.

## Trigger Conditions

Use this skill when the user needs to:

- design a regular block model definition from explicit extents
- inspect and validate any block model definition (regular or subblocked)
- keep local design and inspection separate from Evo persistence

Do not use this skill when:

- the request is about persistence to or retrieval from Evo rather than local block model design or inspection
- the block model already exists in Evo and does not need to be redesigned locally

### Block Model Types

- **Regular**: uniform grid, can be designed locally from extents. Has origin, n_blocks, block_size.
- **Subblocked**: imported from Evo only. Types include fully-sub-blocked, flexible, octree. Has geometry metadata and attribute names but cannot be created locally.

Both types can be staged and inspected locally.

## Tools

All block-model operations use two generic staging tools:

- `staging_create_object(object_type="regular_block_model", params={...})` — design a new regular block model from explicit min/max extents and block sizes.
- `staging_invoke_interaction(object_name="...", interaction_name="get_definition_details")` — inspect and summarize any staged block model (regular or subblocked).

Use the interactions documented in this skill directly. Assume they work. Only call `staging_list_interactions(object_type="regular_block_model")` or `staging_list_interactions(object_type="block_model")` if an invocation fails due to an unknown interaction.

### Available Interactions

| Object type | `interaction_name` | Purpose |
|---|---|---|
| `regular_block_model` | `get_definition_details` | Inspect grid geometry, origin, block size, bounding box. |
| `block_model` | `get_definition_details` | Inspect subblocked geometry metadata and attribute names. |

## Decision Flow

```text
User needs block model help
|
+-- Needs a new block model definition from explicit extents?
|   +-- Yes --> staging_create_object(object_type="regular_block_model", ...)
|
+-- Needs to verify any block model payload? --> staging_invoke_interaction(..., interaction_name="get_definition_details")
|
+-- Needs to import or publish? --> outside this skill's scope
```

## Workflow

1. Choose action path: design from extents or inspect a block model.
2. For design from extents: call `staging_create_object(object_type="regular_block_model", params={...})` with explicit extents and block sizes.
3. For payload inspection: call `staging_invoke_interaction(object_name="...", interaction_name="get_definition_details")`.
4. For padded designs, always report both `requested_bounding_box` and `derived_grid.resulting_bounding_box` from the create response.

## Rules

- Regular block models can be designed locally; subblocked block models are import-only.
- Keep payloads strict and canonical.
- Keep derivation results explicit: origin, n_blocks, block_size, total_blocks, and resulting bounding box.
- Use exact padding parameter names: `padding_x`, `padding_y`, `padding_z`.
- For padding workflows, include both requested padded extents and derived grid extents in the user-facing response.
- Both tools are local operations — no Evo API calls.
- Block sizes (`dx`, `dy`, `dz`) must be greater than zero.
- Extents must have `max > min` on all axes.
- Objects are referenced by name throughout the workflow.
- Use the documented tool path first; do not run discovery calls before execution.

## Gotchas

- Subblocked block models are inspect-only in this workflow; do not attempt local redesign.
- Extents that look valid can still produce unintended coarse/fine grids if block size units are mismatched with CRS/size units.
- Large extents with very small block sizes can create huge total block counts; surface `total_blocks` before downstream use.

## Error Handling

- Non-positive block size (`dx`, `dy`, or `dz` ≤ 0): reject with clear message identifying which dimension is invalid.
- Invalid extents (`min >= max` on any axis): reject and identify the offending axis.
- Zero-volume grid (extents collapse on any axis): reject before computing block counts.
- Block model name not found in session: report that the name could not be resolved and suggest checking staged objects.
- Subblocked block model used with design tool: explain that subblocked block models are import-only and cannot be redesigned locally.

## Required Inputs

- For local design from extents: `params.object_name`, `params.object_path`, `params.block_size_x`, `params.block_size_y`, `params.block_size_z`, `params.x_min`, `params.x_max`, `params.y_min`, `params.y_max`, `params.z_min`, `params.z_max`.
- For payload inspection: `object_name`.

## Optional Inputs

- `params.description`
- `params.padding_x`, `params.padding_y`, `params.padding_z`
- `params.coordinate_reference_system`
- `params.size_unit_id`

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `references/tool_call_reference.md` if a tool invocation fails and you need to verify the exact parameter names or call structure.
- Read `references/payload_contract.md` when you need the canonical regular block model payload shape and exact field names.
