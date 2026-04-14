---
name: point-set-management
description: Builds and inspects point sets locally from CSV data — loads coordinates, validates quality, and summarizes geometry and attributes.
---

# Point Set Management

Use this skill for local point-set handling: build PointSet payloads from CSV, summarize geometry and attributes, and inspect attribute details.

## Trigger Conditions

Use this skill when the user needs to:

- build a point-set payload from CSV coordinates and attributes
- inspect a point-set payload
- inspect point-set attribute columns and null patterns

## When to Use Each Tool

### Quick Selection Guide

- `point_set_build_local`: Build a PointSet payload from CSV with coordinate validation and optional invalid-row dropping.
- `point_set_summarize`: Inspect point count, bounding box, and attribute names from the point set.
- `point_set_attribute_details`: Inspect attribute dtypes, null counts, and preview values.

## Decision Flow

```text
User needs point-set help
|
+-- Has CSV and needs local prep? --> point_set_build_local
|
+-- Needs geometry/attribute QA? --> point_set_summarize (by point_set_name)
|
+-- Needs attribute diagnostics? --> point_set_attribute_details (by point_set_name)
|
+-- Needs to import or publish? --> outside this skill's scope
```

## Workflow

1. Choose the path: build from CSV, summarize, or inspect attributes.
2. For CSV-driven workflows, call `point_set_build_local` first.
3. For QA, call `point_set_summarize` and `point_set_attribute_details` with the point set name.

## Rules

- Keep payloads strict and canonical.
- All tools are local operations — no Evo API calls.
- Use `coordinate_cleaning="drop_invalid"` for robust CSV ingestion unless the user explicitly wants strict failure.
- Surface summary stats before publishing when users ask for data quality confirmation.
- Objects are referenced by name throughout the workflow.

## Tool Chain Examples

### Example 1: Build and inspect local payload

1. Call `point_set_build_local(object_name="Assays", csv_file="path/to/file.csv", x_column="Easting", y_column="Northing", z_column="RL")`.
2. Call `point_set_summarize(point_set_name="Assays")`.
3. Call `point_set_attribute_details(point_set_name="Assays")`.

### Example 2: Build local payload then persist

1. Call `point_set_build_local(object_name="Assays", csv_file="path/to/file.csv", x_column="Easting", y_column="Northing", z_column="RL")`.
2. Publish to Evo using `publish_object`.

## Error Handling

- Missing coordinate columns: fail fast and list missing columns.
- Non-numeric coordinates: fail or drop rows depending on `coordinate_cleaning`.
- Empty payload after cleaning: fail with explicit guidance.

## Required Inputs

- For `point_set_build_local`:
  - `object_name`
  - `csv_file`
  - `x_column`, `y_column`, `z_column`
- For `point_set_summarize`:
  - `point_set_name`
- For `point_set_attribute_details`:
  - `point_set_name`

## Optional Inputs

- `coordinate_cleaning` (`drop_invalid` or `strict`)
- `description`
- `coordinate_reference_system`
- `size_unit_id`
