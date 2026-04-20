# Object Discovery Output Shape

Use this reference only when exact response structure is needed for downstream chaining.

## Top-level fields

- `workspace_id`
- `requested_types`
- `candidates`
- `ambiguities`

## Candidate fields

Each candidate should include:

- `name`
- `path`
- `schema_id`

Internal identifiers (`id`, `version_id`) may be preserved for tool chaining but should not be surfaced in user-facing conversation unless needed to unblock.
