---
name: kriging-reporting
description: Use this skill after a kriging run completes to interpret results, summarize per-scenario estimation outcomes, compare scenario statistics, and surface inspection links. No tool calls — purely interpretive.
---

# Kriging Reporting

Use this skill to interpret and present completed kriging results. Reads structured output from `evo-kriging-execute`, summarizes per-scenario outcomes, and guides the user on next steps. No tool calls — purely interpretive.

## Verification and Limitations

This skill requires the evo-mcp server and its associated tools to function; without them, it is not usable. This skill is assistive and may produce incomplete, incorrect, or variable results over time.

For details, call `get_skills_disclosure` tool or consult the repository disclaimers.

## Trigger Conditions

Use this skill when the user needs to:

- review per-scenario status from a completed kriging run
- see target and attribute outcomes from estimation
- get inspection links for the created or updated target

Do not use this skill when:

- kriging has not been executed yet
- the run inputs or outputs are still incomplete
- the request is about preparing or changing estimation inputs rather than interpreting completed results

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

When the user has multiple scenarios and wants a visual comparison, use `scripts/plot_scenario_comparison_boxplot.py`.
Load the script, map scenario estimate arrays into the script input shape, and present the adapted code as ready to run.

## Rules

- Keep summaries aligned to the input scenario ordering.
- Preserve structured target metadata.
- Prefer concise reporting over verbose narrative.
- Treat tabular or statistics retrieval as a follow-up step.
- When multiple scenarios are reported, number them in order.

## Gotchas

- Multi-scenario runs can be partially successful; never collapse mixed outcomes into a single success/failure statement.
- Scenario order is semantically important and must match input order in summaries.
- Missing inspection links do not invalidate numerical results; report the gap and continue interpretation.

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

## References

Load these files only when the specific condition applies — do not load them proactively:

- Read `scripts/plot_scenario_comparison_boxplot.py` when the user asks to compare scenarios visually.
- Read `references/output_shape.md` when you need exact reporting output contract fields.