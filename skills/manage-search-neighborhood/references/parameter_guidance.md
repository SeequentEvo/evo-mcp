# Search Neighborhood Parameter Guidance

Use this reference to guide range and sample-limit choices

## Choosing Search Ranges

- Rule of thumb: set search ranges to `1.5x` to `3x` the variogram ranges.
- Use `scale_factor=2.0` (moderate) as a default starting point.
- Dense, well-distributed data: tighter search (`~1.5x`) may preserve local trends.
- Sparse or clustered data: broader search (`~3x`) helps reduce unestimated zones.

## Choosing Min Samples

- `2-4`: lower support; can be highly sensitive to individual samples.
- `5-10`: balanced support for stability vs. local variability.
- `10-15`: higher support; smoother estimates, but can suppress real variability and increase runtime.
- Recommended defaults: `4` as the standard starting point.

## Choosing Max Samples

- `5-10`: lower support; faster runs with more local variability, but potentially noisier estimates.
- `15-25`: balanced support for smoothness vs. local detail.
- `30+`: higher support; smoother estimates with diminishing returns and higher runtime.
- Recommended default: `20` for most workflows.

## Diagnostic Tuning

### If search is too small
- Symptom: many unestimated blocks or unstable/high-variance estimates.
- Action: increase range scale (try `3x`) and/or increase `max_samples`.

### If search is too large
- Symptom: overly smooth estimates or slow compute.
- Action: reduce ranges (toward `1.5x`) and/or lower `max_samples`.
