---
name: evo-object-visualisation
description: Generates Evo Viewer and Portal links for point sets, block models, and grids. Does not support variogram or ellipsoid visualisation.
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

## Code-Generated Visualization

Some geoscience objects -- particularly **variograms** and **search ellipsoids** -- are not supported by the Evo Viewer. This skill does not handle visualization for those object types. When a user requests visualization for an unsupported type, explain that it cannot be shown in the Evo Viewer and that code-generated visualization (e.g., plotly) is required.

### Supported Object Types

| Object Type | Evo Viewer? |
|---|---|
| Point sets | [Y] Yes |
| Block models | [Y] Yes |
| Regular 3D grids | [Y] Yes |
| Variogram ellipsoids | [N] Not supported by this skill |
| Variogram curves | [N] Not supported by this skill |
| Search ellipsoids | [N] Not supported by this skill |

## Required Inputs

- `workspace_id`
- `object_ids`

## Error Handling

- Empty object ID list: fail with a message indicating at least one object ID is required.
- Invalid object ID: fail with a resolution error identifying which ID could not be found.
- Workspace not accessible: fail with an explicit workspace resolution message.