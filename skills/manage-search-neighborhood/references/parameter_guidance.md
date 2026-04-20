# Search Neighborhood Parameter Guidance

Use this reference only when the user asks how to tune ranges or sample limits.

## Choosing Search Ranges

- Rule of thumb: set search ranges to `1.5x` to `3x` the variogram ranges.
- Use `scale_factor=2.0` (moderate) as a default starting point.
- Dense, well-distributed data: tighter search (`~1.5x`) may preserve local trends.
- Sparse or clustered data: broader search (`~3x`) helps reduce unestimated zones.

## Choosing Max Samples

- `5-10`: faster, more local variability, potentially noisier estimates.
- `15-25`: balanced default; start with `20` for most workflows.
- `30+`: smoother estimates with diminishing returns and higher runtime.

## Diagnostic Tuning

### If search is too small
- Symptom: many unestimated blocks or unstable/high-variance estimates.
- Action: increase range scale (try `3x`) and/or increase `max_samples`.

### If search is too large
- Symptom: overly smooth estimates or slow compute.
- Action: reduce ranges (toward `1.5x`) and/or lower `max_samples`.
