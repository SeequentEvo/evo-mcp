---
name: design-search-neighborhood
description: Designs search neighborhood ellipsoids for spatial estimation — configures ranges and sample limits, or derives them from variogram parameters.
---

# Design Search Neighborhood

Use this skill to build a `SearchNeighborhood` — the ellipsoid and sample-limit configuration required by spatial estimation tasks. The neighborhood defines how far to search for nearby samples and how many to use.

This skill is local-only for variogram-based and explicit-range inputs. It only contacts Evo when `variogram_object_id` is provided.

## Trigger Conditions

Use this skill when:

- the user needs to configure a search neighborhood for estimation
- ranges need to be derived from a variogram (scaled by a factor)
- the user provides explicit ellipsoid ranges and sample limits
- the user wants the workflow to stay local and avoid Evo service interaction

Do not use this skill when:

- no estimation task is planned
- the user already has a fully configured neighborhood payload
- the user is asking to publish/import variograms (handle separately)

## Input Modes

The skill supports three input modes:

### 1. Explicit Ranges

Provide `major`, `semi_major`, and `minor` directly. All three are required together. Optionally provide `dip_azimuth`, `dip`, `pitch` for rotation.

### 2. Variogram Derivation (Preferred for local workflows)

When a variogram is available (for example, from `variogram_create` or `import_object`), derive ranges from the variogram:

1. Know the variogram name from a prior `variogram_create` or `import_object` call.
2. Call `design_search_neighborhood(variogram_name="CU variogram", scale_factor=2.0, max_samples=20)`.

The tool retrieves the variogram data and scales ranges by `scale_factor`. This keeps the workflow fully local.

### 3. Workspace-Backed (requires workspace_id)

Provide `variogram_object_id` and `workspace_id` to resolve ranges directly from a published Evo variogram object.

## Workflow

1. Determine the range source: explicit values, named variogram, or Evo variogram object.
2. Validate `max_samples >= 1` and, when provided, `min_samples <= max_samples`.
3. Validate that explicit ranges are complete (`major`, `semi_major`, `minor`) and all are positive.
4. Call `design_search_neighborhood` with the appropriate inputs.

## Tool Call Reference

```
design_search_neighborhood(
    max_samples=20,
    min_samples=4,
    variogram_name="CU variogram",
    scale_factor=2.0,
    preset="moderate",        # or "custom", "tight", "broad"
    structure_index=None,     # auto-select by selection_mode
    selection_mode="first",   # or "largest_major"
)
```

## Rules

- The downstream kriging tools automatically normalize the neighborhood output for execution. No manual field renaming is needed when passing results between skills.
- All three explicit ranges (`major`, `semi_major`, `minor`) must be provided together — partial ranges are rejected.
- Prefer `variogram_name` when a variogram is available in the session.
- Do not pass `variogram_object_id` and `variogram_name` together — they are mutually exclusive.
- Use rotation from derived variogram by default; explicit rotation overrides individual angles.
- Do not perform publish/import in this skill; handle those workflows separately.
- Surface derivation metadata (`mode`, `scale_factor`, `variogram_name`) so the user can review how the neighborhood was configured.
- Do not guess sample limits. Ask the user or use reasonable defaults (e.g., `max_samples=20`).

## Parameter Guidance for Geologists

### Choosing Search Ranges
- **Rule of thumb**: Set search ranges to 1.5–3× the variogram ranges.
- Use `scale_factor=2.0` (the moderate preset) as a reliable starting point.
- If your data is dense and well-distributed, a tighter search (1.5×) may capture local trends better.
- If data is sparse or clustered, a broader search (3×) avoids gaps in estimation.

### Choosing Max Samples
- **5–10**: Fast, emphasizes local variation, higher variance in estimates.
- **15–25**: Balanced — start with 20 for most workflows.
- **30+**: Smoother estimates, diminishing returns, slower computation.

### When Search Is Too Small
If kriging estimates show many unestimated blocks or high variance:
- Increase search ranges (try 3× the variogram range).
- Increase `max_samples` to ensure enough samples fall within the ellipsoid.

### When Search Is Too Large
If estimates are overly smooth or computation is slow:
- Reduce search ranges closer to 1.5× the variogram range.
- Reduce `max_samples` to limit the influence radius.

## Error Handling

- Incomplete explicit ranges (only 1 or 2 of major/semi_major/minor provided): reject and list the missing ranges.
- Non-positive explicit range values: reject and identify the invalid range.
- `max_samples < 1`: reject with guidance that at least 1 sample is required.
- `min_samples > max_samples`: reject and suggest correcting the sample limits.
- Both `variogram_name` and `variogram_object_id` provided: reject — these are mutually exclusive sources.
- Variogram name not found in session: report that the named variogram could not be resolved.
- No range source provided (no explicit ranges, no variogram name, no variogram object ID): reject and explain the available input modes.

## Required Inputs

- `max_samples`
- One of:
  - explicit `major`, `semi_major`, `minor`
  - `variogram_name` (named variogram — derives scaled ranges)
  - `variogram_object_id` + `workspace_id` (Evo-backed)

## Optional Inputs

- `min_samples`
- `dip_azimuth`, `dip`, `pitch` (rotation override)
- `scale_factor` (default 1.0; use 2.0 for moderate neighborhood)
- `preset` (`tight`=1×, `moderate`=2×, `broad`=3×, `custom`=scale_factor)
- `structure_index`, `selection_mode`

## Output Shape

```
{
    "neighborhood": {
        "ellipsoid": {
            "ellipsoid_ranges": { "major": ..., "semi_major": ..., "minor": ... },
            "rotation": { "dip_azimuth": ..., "dip": ..., "pitch": ... }
        },
        "max_samples": ...,
        "min_samples": ...
    },
    "derivation": {
        "mode": "user-specified" | "variogram-scaled" | "variogram-object-scaled",
        "scale_factor": ...,
        "variogram_name": "...",   # present when mode=variogram-scaled
        "selected_structure_index": 0,
        "selected_by": "first" | "largest_major" | "structure_index"
    }
}
```

**Note:** The neighborhood output is passed directly to downstream kriging tools, which handle any field normalization automatically.