---
name: design-search-neighborhood
description: Use this skill when the user needs to configure a search neighborhood for spatial estimation — whether providing explicit ellipsoid ranges or deriving them from a variogram. Use even when the user just says "set up the search" or "how far should I search?"
---

# Search Neighborhood

Use this skill to build a `SearchNeighborhood` — the ellipsoid and sample-limit configuration required by spatial estimation tasks. The neighborhood defines how far to search for nearby samples and how many to use.

This skill is local-only. All operations work against locally staged objects — no Evo API calls.

## Verification and Limitations

This skill requires the evo-mcp server and its associated tools to function; without them, it is not usable. This skill is assistive and may produce incomplete, incorrect, or variable results over time.

For details, call `get_skills_disclosure` tool or consult the repository disclaimers.

## Trigger Conditions

Use this skill when:

- the user needs to configure a search neighborhood for estimation
- ranges need to be derived from a variogram (scaled by a factor)
- the user provides explicit ellipsoid ranges and sample limits

Do not use this skill when:

- no estimation task is planned
- the user already has a fully configured neighborhood payload
- the request is about persistence or object-state changes rather than local neighborhood configuration

## Tools

| Tool | Use |
|---|---|
| `staging_create_object` | Build the neighborhood from explicit ellipsoid ranges (Path A) |
| `staging_invoke_interaction` | Derive and create the neighborhood from a staged variogram in one step (Path B) |

## Workflow

### Option A — Build manually from explicit ranges

1. Collect `object_name`, `max_samples`, and all three ellipsoid ranges (`major`, `semi_major`, `minor`) from the user. Optionally collect `min_samples` and rotation (`dip_azimuth`, `dip`, `pitch`).
2. Call `staging_create_object` with `object_type="search_neighborhood"`.

### Option B — Derive automatically from a staged variogram *(preferred)*

1. Confirm a variogram is staged in-session. Create or import one otherwise.
2. Collect `object_name` and `max_samples`. Optionally collect `min_samples`, `scale_factor`, `structure_index`, `selection_mode`, and rotation overrides.
3. Call `staging_invoke_interaction` with `interaction_name="create_search_neighborhood"` on the variogram object. This derives the ellipsoid from the variogram's anisotropy structure and stages the neighborhood in one step.

## Rules

- The downstream kriging tools automatically normalize the neighborhood output for execution. No manual field renaming is needed when passing results between skills.
- Prefer variogram derivation (Path B) when a variogram is staged in the session.
- Do not perform publish/import in this skill.
- Surface derivation metadata (`variogram_name`, `selected_structure_index`, `scale_factor`) so the user can review how the neighborhood was configured.
- Do not guess sample limits. Ask the user or use reasonable defaults (e.g., `max_samples=20`).

## Gotchas

- Partial explicit ranges are invalid; all of `major`, `semi_major`, and `minor` must be present together.
- `min_samples` greater than `max_samples` is a common setup error and should be corrected before execution.
- If a variogram name is stale or misspelled, derivation will fail even when the object exists in Evo but is not staged in-session.
- Path B (`create_search_neighborhood`) is an interaction on the **variogram** — pass the variogram's `object_name` to `staging_invoke_interaction`, not `"search_neighborhood"`.

## Error Handling

- Incomplete explicit ranges (only 1 or 2 of major/semi_major/minor provided): reject and list the missing ranges.
- Non-positive explicit range values: reject and identify the invalid range.
- `max_samples < 1`: reject with guidance that at least 1 sample is required.
- `min_samples > max_samples`: reject and suggest correcting the sample limits.
- Variogram not staged: report that the named variogram could not be resolved and offer to stage it first.
- No range source provided (no explicit ranges, no staged variogram): reject and explain the two available paths.

