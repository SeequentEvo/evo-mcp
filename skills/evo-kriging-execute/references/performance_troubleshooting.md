# Performance Troubleshooting

Use this reference when kriging runs are slow, time out, or leave many blocks unestimated.

## If runtime is too long

- Reduce target block count (coarser block size).
- Reduce `max_samples` (for example, 12 to 16 instead of 20+).
- Reduce search ranges to limit candidate samples.
- Reduce number of scenarios per batch.

## If many blocks are unestimated

- Increase search ranges to capture more nearby samples.
- Lower `min_samples` to allow estimation in sparse zones.
- Check source data coverage against target extents.

## Practical tuning order

1. Fix obvious coverage gaps first.
2. Tune neighborhood ranges and sample counts.
3. Only then increase scenario complexity.
