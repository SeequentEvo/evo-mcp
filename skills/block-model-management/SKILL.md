---
name: block-model-management
description: Designs regular block models from extents and block sizes. Inspects block model definitions and validates grid parameters locally.
---

# Block Model Management

Use this skill for local block model handling: design regular block model definitions from explicit extents and inspect block model payloads.

## Trigger Conditions

Use this skill when the user needs to:

- design a regular block model definition from explicit extents
- inspect and validate any block model definition (regular or subblocked)
- keep local design and inspection separate from Evo persistence

## Block Model Types

- **Regular**: uniform grid, can be designed locally from extents. Has origin, n_blocks, block_size.
- **Subblocked**: imported from Evo only. Types include fully-sub-blocked, flexible, octree. Has geometry metadata and attribute names but cannot be created locally.

Both types can be staged and inspected locally.

## When to Use Each Tool

### Quick Selection Guide

- `regular_block_model_design_from_extents`: Design a new regular block model from explicit min/max extents and block sizes.
- `block_model_get_definition_details`: Inspect and summarize any staged block model (regular or subblocked).

## Decision Flow

```text
User needs block model help
|
+-- Needs a new block model definition from explicit extents?
|   +-- Yes --> regular_block_model_design_from_extents
|
+-- Needs to verify any block model payload? --> block_model_get_definition_details
|
+-- Needs to import or publish? --> outside this skill's scope
```

## Workflow

1. Choose action path: design from extents or inspect a block model.
2. For design from extents: call `regular_block_model_design_from_extents` with explicit extents and block sizes.
3. For payload inspection: call `block_model_get_definition_details` with the block model name.

## Rules

- Regular block models can be designed locally; subblocked block models are import-only.
- Keep payloads strict and canonical.
- Keep derivation results explicit: origin, n_blocks, block_size, total_blocks, and resulting bounding box.
- Both tools are local operations — no Evo API calls.
- Block sizes (`dx`, `dy`, `dz`) must be greater than zero.
- Extents must have `max > min` on all axes.
- Objects are referenced by name throughout the workflow.

## Payload Contract

Canonical regular block model payload:

```json
{
  "name": "Grade Block Model",
  "description": "Optional description",
  "coordinate_reference_system": "EPSG:32632",
  "size_unit_id": "m",
  "origin": {"x": 1000.0, "y": 2000.0, "z": 300.0},
  "n_blocks": {"nx": 80, "ny": 60, "nz": 20},
  "block_size": {"dx": 25.0, "dy": 25.0, "dz": 10.0}
}
```

## Error Handling

- Non-positive block size (`dx`, `dy`, or `dz` ≤ 0): reject with clear message identifying which dimension is invalid.
- Invalid extents (`min >= max` on any axis): reject and identify the offending axis.
- Zero-volume grid (extents collapse on any axis): reject before computing block counts.
- Block model name not found in session: report that the name could not be resolved and suggest checking staged objects.
- Subblocked block model used with design tool: explain that subblocked block models are import-only and cannot be redesigned locally.

## Required Inputs

- Local design from extents:
- `object_name`, `object_path`
- `block_size_x`, `block_size_y`, `block_size_z`
- `x_min`, `x_max`, `y_min`, `y_max`, `z_min`, `z_max`

## Optional Inputs

- `description`
- `padding_x`, `padding_y`, `padding_z`
- `coordinate_reference_system`
- `size_unit_id`

## Tool Chain Examples

### Example 1: Design locally from explicit extents

1. Call `regular_block_model_design_from_extents(object_name="Domain BM", object_path="/blockmodels/domain_bm.json", block_size_x=25, block_size_y=25, block_size_z=10, x_min=1000, x_max=3000, y_min=2000, y_max=3500, z_min=100, z_max=600)`.
2. Review `derived_grid.total_blocks` and `derived_grid.resulting_bounding_box`.
3. Call `block_model_get_definition_details(block_model_name="Domain BM")` to validate the payload.

### Example 2: Derive from source bounds then publish

1. Design the block model using `regular_block_model_design_from_extents(...)` with the desired extents.
2. Review the block model payload locally.
3. Publish to Evo using `publish_object`.
