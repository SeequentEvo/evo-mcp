---
name: evo-object-management
description: Import and publish geoscience objects between the local session and Evo. Manages variogram, point set, and block model import/publish workflows.
---

# Object Management

This skill manages the **Evo boundary** — importing objects from Evo into the local session and publishing local objects back to Evo.

## Tools

- `variogram_import` / `variogram_publish`
- `point_set_import` / `point_set_publish`
- `block_model_import` / `regular_block_model_publish`

## Trigger Conditions

Use this skill when the user needs to:

- import a geoscience object from Evo into the session
- publish a local object to Evo (create or new version)

For local-only object creation and inspection, use the domain skills:
- `variogram-management` for variogram creation/inspection
- `point-set-management` for point set building/inspection
- `block-model-management` for block model design/inspection

## Workflow

1. Confirm `workspace_id` and object role.
2. Use `evo-object-discovery` to locate objects if needed.
3. Import with the appropriate `*_import` tool, or publish with `*_publish`.

## Notes

- Standard (non-regular) block models can be imported but not published.
- Only regular block models can be published to Evo.

## Error Handling

- Invalid workspace or object IDs: fail with explicit resolution message.
- Object role mismatch: fail with expected type in message.
