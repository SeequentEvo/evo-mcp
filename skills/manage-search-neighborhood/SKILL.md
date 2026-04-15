---
name: manage-search-neighborhood
description: Use this skill when the user needs to configure a search neighborhood for spatial estimation — whether providing explicit ellipsoid ranges or deriving them from a variogram. Use even when the user just says "set up the search" or "how far should I search?"
---

# Search Neighborhood

Use this skill to build a `SearchNeighborhood` — the ellipsoid and sample-limit configuration required by spatial estimation tasks. The neighborhood defines how far to search for nearby samples and how many to use.

This skill is local-only. All operations work against locally staged objects — no Evo API calls.

## Trigger Conditions

Use this skill when:

- the user needs to configure a search neighborhood for estimation
- ranges need to be derived from a variogram (scaled by a factor)
- the user provides explicit ellipsoid ranges and sample limits
- the user wants the workflow to stay local and avoid Evo service interaction

Do not use this skill when:

- no estimation task is planned
- the user already has a fully configured neighborhood payload
- the request is about persistence or object-state changes rather than local neighborhood configuration

## Tools

All search neighborhood operations use a single generic staging tool:

- `staging_create_object(object_type="search_neighborhood", params={...})` — build a search neighborhood from explicit ranges or a staged variogram.

Use the documented tool path directly. Only call `staging_list_object_types` if the tool type is unclear.

## Decision Flow

```text
User needs search neighborhood
|
+-- Has explicit ranges (major/semi_major/minor)?
|   --> staging_create_object(object_type="search_neighborhood", params={major, semi_major, minor, ...})
|
+-- Has a staged variogram?
|   --> staging_create_object(object_type="search_neighborhood", params={variogram_name, scale_factor, ...})
|
+-- Needs variogram first? --> use manage-variogram or staging-workflow, then return here
```

### Input Modes

The skill supports two input modes:

### 1. Explicit Ranges

Provide `major`, `semi_major`, and `minor` directly. All three are required together. Optionally provide `dip_azimuth`, `dip`, `pitch` for rotation.

### 2. Variogram Derivation (Preferred)

When a variogram is staged locally (for example, from `staging_create_object(object_type="variogram", ...)` or imported via `staging_import_object`), derive ranges from it:

1. Know the variogram name from a prior create or import call.
2. Call `staging_create_object(object_type="search_neighborhood", params={"variogram_name": "CU variogram", "scale_factor": 2.0, "max_samples": 20})`.

## Workflow

1. Determine the range source: explicit values or named staged variogram.
2. Validate `max_samples >= 1` and, when provided, `min_samples <= max_samples`.
3. Validate that explicit ranges are complete (`major`, `semi_major`, `minor`) and all are positive.
4. Call `staging_create_object(object_type="search_neighborhood", params={...})` with the appropriate inputs.

## Rules

- The downstream kriging tools automatically normalize the neighborhood output for execution. No manual field renaming is needed when passing results between skills.
- All three explicit ranges (`major`, `semi_major`, `minor`) must be provided together — partial ranges are rejected.
- Prefer `variogram_name` when a variogram is staged in the session.
- Do not perform publish/import in this skill.
- Surface derivation metadata (`mode`, `scale_factor`, `variogram_name`) so the user can review how the neighborhood was configured.
- Do not guess sample limits. Ask the user or use reasonable defaults (e.g., `max_samples=20`).
- Use this documented tool path directly; do not run discovery calls first.
- Only run discovery/listing if tool invocation fails and you need to troubleshoot accepted fields.

## Gotchas

- Partial explicit ranges are invalid; all of `major`, `semi_major`, and `minor` must be present together.
- `min_samples` greater than `max_samples` is a common setup error and should be corrected before execution.
- If a variogram name is stale or misspelled, derivation will fail even when the object exists in Evo but is not staged in-session.
- Overly broad neighborhoods can smooth estimates and increase runtime; overly tight neighborhoods can leave blocks unestimated.

## Error Handling

- Incomplete explicit ranges (only 1 or 2 of major/semi_major/minor provided): reject and list the missing ranges.
- Non-positive explicit range values: reject and identify the invalid range.
- `max_samples < 1`: reject with guidance that at least 1 sample is required.
- `min_samples > max_samples`: reject and suggest correcting the sample limits.
- Variogram name not found in session: report that the named variogram could not be resolved.
- No range source provided (no explicit ranges, no variogram name): reject and explain the two available input modes.

## Required Inputs

- `max_samples`
- One of:
  - explicit `major`, `semi_major`, `minor`
  - `variogram_name` (staged variogram — derives scaled ranges)

## Optional Inputs

- `min_samples`
- `dip_azimuth`, `dip`, `pitch` (rotation override)
- `scale_factor` (default 1.0; use 2.0 for moderate neighborhood)
- `preset` (`tight`=1×, `moderate`=2×, `broad`=3×, `custom`=scale_factor)
- `structure_index`, `selection_mode`

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `references/tool_call_reference.md` if a tool invocation fails and you need to verify the exact parameter names or call structure.
- Read `references/parameter_guidance.md` when the user asks how to tune ranges or sample limits.
- Read `references/payload_contract.md` when you need exact input/output field contracts for neighborhood creation.