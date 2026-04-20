# Object Visualisation Error Patterns

Use this reference only when `viewer_generate_multi_object_links` fails.

## Common failures and responses

- Empty `object_ids`:
  - Response: request at least one object ID.

- Invalid object ID(s):
  - Response: report which IDs failed resolution and ask for corrected IDs.

- Workspace access issue:
  - Response: report workspace resolution/access error and ask for a valid accessible workspace.

- Variogram visualization requested:
  - Response: explain that variograms are currently unsupported by this path.
