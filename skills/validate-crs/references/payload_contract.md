# Validate CRS Output Contract

Use this reference only when exact output field semantics are needed.

## Output Shape

`staging_spatial_validation` result should be reported with:

- `status`
- `message`
- `source`
- `target`
- `next_action`

## `next_action` Semantics

- `continue`: CRS is compatible; estimation workflow may continue.
- `confirm`: CRS status is unknown; require explicit user confirmation before continuing.
- `stop`: CRS mismatch; stop estimation workflow until resolved or explicitly overridden by user policy.
