---
name: kriging-reporting
description: Reports and interprets completed kriging results — estimation outcomes, attribute statistics, scenario comparisons, and inspection links.
---

# Kriging Reporting

Use this skill after kriging estimation has completed.

## Trigger Conditions

Use this skill when the user needs to:

- review per-scenario status from a completed kriging run
- see target and attribute outcomes from estimation
- get inspection links for the created or updated target

## Workflow

1. Read the structured results from the completed kriging run.
2. Report each scenario in order.
3. Highlight the target name, attribute operation, and attribute name.
4. Surface inspection links.
5. Suggest the next follow-up action, such as retrieving target data or visualizing estimates.

## Results Interpretation

### Key Statistics
- **mean**: Average estimated value across the target — the central tendency of your grade model.
- **std**: Standard deviation — higher values indicate more variability in estimates.
- **min/max**: Range of estimated values.
- **q25/median/q75**: Distribution quartiles — useful for spotting skewness in the grade distribution.

### Comparing Scenarios
When the user runs multiple scenarios (e.g., varying `max_samples`, methods, or neighborhoods):
- Higher `max_samples` typically produces lower standard deviation (smoother results).
- The mean should remain relatively stable across scenarios if the variogram model is robust.
- Large differences in mean across scenarios suggest sensitivity to the neighborhood size or kriging method.
- Ordinary vs simple kriging: differences highlight how the local mean assumption affects estimates.

### Scenario Comparison Visualization

When the user has multiple scenarios and wants a visual comparison, generate a plotly box plot:

```python
import plotly.express as px
import pandas as pd

# Each column represents estimated values from a scenario
df = pd.DataFrame({
    "OK_estimate": ok_values,
    "SK_estimate": sk_values,
})

df_melted = df.melt(var_name="Scenario", value_name="Estimated Value")
fig = px.box(df_melted, x="Scenario", y="Estimated Value",
             title="Kriging Results by Scenario")
fig.show()
```

Use this when the user asks to "compare", "contrast", or "see the difference" between scenarios.

## Rules

- Keep summaries aligned to the input scenario ordering.
- Preserve structured target metadata.
- Prefer concise reporting over verbose narrative.
- Treat tabular or statistics retrieval as a follow-up step.
- When multiple scenarios are reported, number them in order.

## Required Inputs

- Structured results from a completed kriging run

## Output Shape

- `status`
- `scenario_summaries` (one per scenario, in input order)
- `inspection_links` (portal and viewer URLs per target)
- `next_step_guidance` (suggested follow-up actions)
- `comparison_visualization` (when multiple scenarios are present — plotly code for comparison)

## Error Handling

- No kriging results available: report that kriging must be executed first.
- Partial failures in multi-scenario runs: report which scenarios succeeded and which failed, with per-scenario detail.
- Missing inspection links: note the absence and suggest checking the target object directly in Evo.