# Scenario Patterns

Use this reference when the user wants comparative kriging runs in one batch.

## Pattern 1: Multiple target attributes

Keep source, variogram, and neighborhood fixed. Change only `params.target_attribute` per scenario.

## Pattern 2: Multiple target domains

Keep source, variogram, and neighborhood fixed. Change `params.target_region_filter` per scenario.

## Pattern 3: Method comparison

Use one scenario with ordinary kriging and one with simple kriging.

Simple kriging example method payload:

```json
{"type": "simple", "mean": 1.25}
```

## Pattern 4: Neighborhood sensitivity

Keep source, variogram, and method fixed. Change neighborhood settings between scenarios.

## Batch execution reminder

1. Build each scenario separately with `kriging_build_parameters`.
2. Append each returned payload to `scenarios` in intended comparison order.
3. Execute once with `kriging_run(workspace_id, scenarios)`.
4. Interpret results in the same order as input scenarios.
