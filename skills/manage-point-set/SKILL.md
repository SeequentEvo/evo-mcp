---
name: manage-point-set
description: Use this skill when the user has a CSV file with sample coordinates and wants to prepare a point set for spatial estimation — including loading, QA, and attribute inspection. Do not use when the point set already exists in Evo.
---

# Point Set Management

Use this skill for local point-set handling: build PointSet payloads from CSV, summarize geometry and attributes, and inspect attribute details. All operations are local — no Evo API calls.

## Trigger Conditions

Use this skill when the user needs to:

- build a point-set payload from CSV coordinates and attributes
- inspect a point-set payload
- inspect point-set attribute columns and null patterns

Do not use this skill when:

- the request is about persistence to or retrieval from Evo rather than local point-set preparation
- the point set is already staged and needs no changes

## Tools

All point-set operations use two generic staging tools:

- `staging_create_object(object_type="point_set", params={...})` — build a PointSet payload from CSV with coordinate validation and optional invalid-row dropping.
- `staging_invoke_interaction(object_name="...", interaction_name="...", params={...})` — call any inspection interaction on a staged point set.

Use the interactions documented in this skill directly. Assume they work. Only call `staging_list_interactions(object_type="point_set")` if an invocation fails due to an unknown interaction.

### Available Interactions

| `interaction_name` | Purpose |
|---|---|
| `get_summary` | Inspect point count, bounding box, and attribute names. |
| `get_attribute_details` | Inspect attribute dtypes, null counts, and preview values. |

## Decision Flow

```text
User needs point-set help
|
+-- Has CSV and needs local prep? --> staging_create_object(object_type="point_set", ...)
|
+-- Needs geometry/attribute QA? --> staging_invoke_interaction(..., interaction_name="get_summary")
|
+-- Needs attribute diagnostics? --> staging_invoke_interaction(..., interaction_name="get_attribute_details")
|
+-- Needs to import or publish? --> outside this skill's scope
```

## Workflow

1. Choose the path: build from CSV, summarize, or inspect attributes.
2. For CSV-driven workflows, call `staging_create_object(object_type="point_set", params={...})` first.
3. For QA, call `staging_invoke_interaction(object_name="...", interaction_name="get_summary")` and `staging_invoke_interaction(object_name="...", interaction_name="get_attribute_details")`.

## Rules

- Keep payloads strict and canonical.
- All tools are local operations — no Evo API calls.
- Use `coordinate_cleaning="drop_invalid"` in `params` for robust CSV ingestion unless the user explicitly wants strict failure.
- Surface summary stats before publishing when users ask for data quality confirmation.
- Objects are referenced by name throughout the workflow.

## Gotchas

- Coordinate columns must be numeric after cleaning; string-formatted coordinates are a common failure source.
- `coordinate_cleaning="drop_invalid"` can remove many rows silently if input quality is poor — report dropped-row impact before continuing.
- A point set can be structurally valid but still unusable for estimation if key grade attributes are mostly null; check attribute details when quality is uncertain.

## Error Handling

- Missing coordinate columns: fail fast and list missing columns.
- Non-numeric coordinates: fail or drop rows depending on `coordinate_cleaning`.
- Empty payload after cleaning: fail with explicit guidance.

## Required Inputs

- For `staging_create_object(object_type="point_set", ...)`:
  - `params.object_name`
  - `params.csv_file`
  - `params.x_column`, `params.y_column`, `params.z_column`
- For `staging_invoke_interaction` with `get_summary` or `get_attribute_details`:
  - `object_name`

## Optional Inputs

- `params.coordinate_cleaning` (`drop_invalid` or `strict`)
- `params.description`
- `params.coordinate_reference_system`
- `params.size_unit_id`

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `references/tool_call_reference.md` if a tool invocation fails and you need to verify the exact parameter names or call structure.
