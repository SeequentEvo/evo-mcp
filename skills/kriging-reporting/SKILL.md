---
name: kriging-reporting
description: Report completed kriging runs with structured outcomes, inspection links, and room for richer reporting workflows.
---

# Kriging Reporting

Use this skill after `evo-kriging-run` completes.

## Goals

- report per-scenario status clearly
- surface target and attribute outcomes
- return inspection links for the created or updated target

## Workflow

1. Read the structured results returned by `evo-kriging-run`.
2. Report each scenario in order.
3. Highlight the target name, attribute operation, and attribute name.
4. Surface inspection links.
5. Suggest the next follow-up action, such as retrieving target data.

## Rules

- Keep summaries aligned to the input scenario ordering.
- Preserve structured target metadata.
- Prefer concise reporting over verbose narrative.
- Treat tabular or statistics retrieval as a follow-up step.

## Output Shape

- `status`
- `scenario_summaries`
- `inspection_links`
- `next_step_guidance`