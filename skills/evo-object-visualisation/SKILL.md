---
name: evo-object-visualisation
description: Generate a combined Evo Viewer link and per-object Portal links for explicit object lists. Use this for generic object visualisation workflows, not only kriging.
---

# Object Visualisation

Use this skill to build a combined viewer link from user-supplied object IDs.

## Trigger Conditions

Use this skill when the user wants to:

- view multiple objects together
- generate viewer links from explicit object IDs
- generate portal links for each object in the same response

## Workflow

1. Confirm the `workspace_id`.
2. Confirm the explicit object ID list.
3. Call `viewer_generate_multi_object_links`.
4. Return the combined viewer URL and per-object portal URLs.

## Rules

- This skill is generic and not kriging-specific.
- Require explicit user-supplied object IDs.
- Do not infer or discover objects unless the user asks for that separately.

## Required Inputs

- `workspace_id`
- `object_ids`