# Kriging Reporting Output Shape

Use this reference only when exact reporting contract fields are required.

## Output fields

- `status`
- `scenario_summaries` (ordered to match scenario input)
- `inspection_links` (portal/viewer URLs per target where available)
- `next_step_guidance`
- `comparison_visualization` (optional; when scenario comparison plotting is requested)

## Notes

- Preserve scenario ordering from run input.
- Report partial success/failure per scenario when mixed outcomes occur.
